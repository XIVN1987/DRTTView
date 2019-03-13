#! python2
#coding: utf-8
import os
import sys
import struct
import ConfigParser

import sip
sip.setapi('QString', 2)
from PyQt4 import QtCore, QtGui, uic
from PyQt4.Qwt5 import QwtPlot, QwtPlotCurve

from daplink import coresight, pyDAPAccess


class RingBuffer(object):
    def __init__(self, arr):
        self.sName, self.pBuffer, self.SizeOfBuffer, self.WrOff, self.RdOff, self.Flags = arr
    
    def __str__(self):
        return 'Buffer Address = 0x%08X\nBuffer Size    = %d\nWrite Offset   = %d\nRead Offset    = %d\n' %(self.pBuffer, self.SizeOfBuffer, self.WrOff, self.RdOff)


'''
from RTTView_UI import Ui_RTTView
class RTTView(QtGui.QWidget, Ui_RTTView):
    def __init__(self, parent=None):
        super(RTTView, self).__init__(parent)
        
        self.setupUi(self)
'''
class RTTView(QtGui.QWidget):
    def __init__(self, parent=None):
        super(RTTView, self).__init__(parent)
        
        uic.loadUi('RTTView.ui', self)

        self.initSetting()

        self.initQwtPlot()

        self.daplink = None
        
        self.tmrRTT = QtCore.QTimer()
        self.tmrRTT.setInterval(10)
        self.tmrRTT.timeout.connect(self.on_tmrRTT_timeout)
        self.tmrRTT.start()

        self.tmrCntr = 0    # tmrRTT超时一次，tmrCntr加一
    
    def initSetting(self):
        if not os.path.exists('setting.ini'):
            open('setting.ini', 'w')
        
        self.conf = ConfigParser.ConfigParser()
        self.conf.read('setting.ini')
        
        if not self.conf.has_section('Memory'):
            self.conf.add_section('Memory')
            self.conf.set('Memory', 'StartAddr', '0x20000000')

        self.linAddr.setText(self.conf.get('Memory', 'StartAddr'))

    def initQwtPlot(self):
        self.PlotBuff = ''
        self.PlotData = [0]*1000
        
        self.qwtPlot = QwtPlot(self)
        self.vLayout0.insertWidget(0, self.qwtPlot)
        
        self.PlotCurve = QwtPlotCurve()
        self.PlotCurve.attach(self.qwtPlot)
        self.PlotCurve.setData(range(1, len(self.PlotData)+1), self.PlotData)

        self.on_cmbMode_currentIndexChanged(u'文本显示')
    
    @QtCore.pyqtSlot()
    def on_btnOpen_clicked(self):
        if self.btnOpen.text() == u'打开连接':
            try:
                self.daplink.open()

                self.dp = coresight.dap.DebugPort(self.daplink)
                self.dp.init()
                self.dp.power_up_debug()

                self.ap = coresight.ap.AHB_AP(self.dp, 0)
                self.ap.init()
                
                Addr = int(self.linAddr.text(), 16)
                for i in range(256):
                    buff = self.ap.readBlockMemoryUnaligned8(Addr + 1024*i, 1024)
                    buff = ''.join([chr(x) for x in buff])
                    index = buff.find('SEGGER RTT')
                    if index != -1:
                        self.RTTAddr = Addr + 1024*i + index
                        print '_SEGGER_RTT @ 0x%08X' %self.RTTAddr
                        break
                else:
                    raise Exception('Can not find _SEGGER_RTT')
            except Exception as e:
                print e
            else:
                self.btnOpen.setText(u'关闭连接')
                self.lblOpen.setPixmap(QtGui.QPixmap("./Image/inopening.png"))
        else:
            self.btnOpen.setText(u'打开连接')
            self.lblOpen.setPixmap(QtGui.QPixmap("./Image/inclosing.png"))
                
    def aUpEmpty(self):
        LEN = (16 + 4*2) + (4*6) * 4
        
        buf =  self.ap.readBlockMemoryUnaligned8(self.RTTAddr, LEN)
        
        arr = struct.unpack('16sLLLLLLLL24xLLLLLL24x', ''.join([chr(x) for x in buf]))
        
        self.aUp = RingBuffer(arr[3:9])

        print 'WrOff=%d, RdOff=%d' %(self.aUp.WrOff, self.aUp.RdOff)
        
        self.aDown = RingBuffer(arr[9:15])
        
        return (self.aUp.RdOff == self.aUp.WrOff)
    
    def aUpRead(self):
        if self.aUp.RdOff < self.aUp.WrOff:
            len_ = self.aUp.WrOff - self.aUp.RdOff
            
            arr =  self.ap.readBlockMemoryUnaligned8(self.aUp.pBuffer + self.aUp.RdOff, len_)
            
            self.aUp.RdOff += len_

            self.ap.write32(self.RTTAddr + (16 + 4*2) + 4*4, self.aUp.RdOff)
        else:
            len_ = self.aUp.SizeOfBuffer - self.aUp.RdOff + 1
            
            arr =  self.ap.readBlockMemoryUnaligned8(self.aUp.pBuffer + self.aUp.RdOff, len_)
                        
            self.aUp.RdOff = 0  #这样下次再读就会进入执行上个条件
            
            self.ap.write32(self.RTTAddr + (16 + 4*2) + 4*4, self.aUp.RdOff)
        
        return ''.join([chr(x) for x in arr])
    
    def on_tmrRTT_timeout(self):
        if self.btnOpen.text() == u'关闭连接':
            if not self.aUpEmpty():
                str = self.aUpRead()

                if self.mode == u'文本显示':
                    if len(self.txtMain.toPlainText()) > 50000: self.txtMain.clear()
                    self.txtMain.moveCursor(QtGui.QTextCursor.End)
                    self.txtMain.insertPlainText(str)
                    
                elif self.mode == u'波形显示':
                    self.PlotBuff += str
                    if self.PlotBuff.rfind(',') == -1: return
                    try:
                        d = [int(x) for x in self.PlotBuff[0:self.PlotBuff.rfind(',')].split(',')]
                        for x in d:
                            self.PlotData.pop(0)
                            self.PlotData.append(x)        
                    except:
                        self.PlotBuff = ''
                    else:
                        self.PlotBuff = self.PlotBuff[self.PlotBuff.rfind(',')+1:]
                    
                    self.PlotCurve.setData(range(1, len(self.PlotData)+1), self.PlotData)
                    self.qwtPlot.replot()

        self.detect_daplink()   # 自动检测 DAPLink 的热插拔

    def detect_daplink(self):
        daplinks = pyDAPAccess.DAPAccess.get_connected_devices()
        
        if self.daplink and (daplinks == []):   # daplink被拔下
            try:
                self.daplink.close()
            except Exception as e:
                print e
            finally:
                self.daplink = None
                self.linDAP.clear()

                self.btnOpen.setText(u'打开连接')
                self.lblOpen.setPixmap(QtGui.QPixmap("./Image/inclosing.png"))
        
        if not self.daplink and daplinks != []:
            self.daplink = daplinks[0]

            self.linDAP.clear()
            self.linDAP.setText(self.daplink._product_name)

    @QtCore.pyqtSlot(str)
    def on_cmbMode_currentIndexChanged(self, str):
        self.mode = str
        self.txtMain.setVisible(self.mode == u'文本显示')
        self.qwtPlot.setVisible(self.mode == u'波形显示')
    
    @QtCore.pyqtSlot()
    def on_btnClear_clicked(self):
        self.txtMain.clear()
    
    def closeEvent(self, evt):
        self.conf.set('Memory', 'StartAddr', self.linAddr.text())   
        self.conf.write(open('setting.ini', 'w'))


if __name__ == "__main__":
    app = QtGui.QApplication(sys.argv)
    rtt = RTTView()
    rtt.show()
    app.exec_()
