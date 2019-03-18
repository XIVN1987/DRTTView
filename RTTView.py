#! python2
#coding: utf-8
import os
import sys
import struct
import logging
import collections
import ConfigParser

import sip
sip.setapi('QString', 2)
from PyQt4 import QtCore, QtGui, uic
from PyQt4.Qwt5 import QwtPlot, QwtPlotCurve

from pyocd import coresight
from pyocd.probe import aggregator


os.environ['PATH'] = os.path.dirname(os.path.abspath(__file__)) + os.pathsep + os.environ['PATH']


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

        self.rcvbuff = b''

        self.daplink = None

        self.tmrRTT = QtCore.QTimer()
        self.tmrRTT.setInterval(10)
        self.tmrRTT.timeout.connect(self.on_tmrRTT_timeout)
        self.tmrRTT.start()

        self.tmrRTT_Cnt = 0
    
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
        self.PlotData = [0]*1000
        
        self.qwtPlot = QwtPlot(self)
        self.qwtPlot.setVisible(False)
        self.vLayout0.insertWidget(0, self.qwtPlot)
        
        self.PlotCurve = QwtPlotCurve()
        self.PlotCurve.attach(self.qwtPlot)
        self.PlotCurve.setData(range(1, len(self.PlotData)+1), self.PlotData)
    
    @QtCore.pyqtSlot()
    def on_btnOpen_clicked(self):
        if self.btnOpen.text() == u'打开连接':
            try:
                self.daplink = self.daplinks[self.cmbDAP.currentText()]
                self.daplink.open()
                
                dp = coresight.dap.DebugPort(self.daplink, None)
                dp.init()
                dp.power_up_debug()

                ap = coresight.ap.AHB_AP(dp, 0)
                ap.init()

                self.dap = coresight.cortex_m.CortexM(None, ap)
                
                Addr = int(self.linAddr.text(), 16)
                for i in range(256):
                    buff = self.dap.read_memory_block8(Addr + 1024*i, 1024)
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
                self.cmbDAP.setEnabled(False)
                self.btnOpen.setText(u'关闭连接')
                self.lblOpen.setPixmap(QtGui.QPixmap("./image/inopening.png"))
        else:
            self.daplink.close()
            self.cmbDAP.setEnabled(True)
            self.btnOpen.setText(u'打开连接')
            self.lblOpen.setPixmap(QtGui.QPixmap("./image/inclosing.png"))
    
    def aUpEmpty(self):
        LEN = (16 + 4*2) + (4*6) * 4
        
        buf =  self.dap.read_memory_block8(self.RTTAddr, LEN)
        
        arr = struct.unpack('16sLLLLLLLL24xLLLLLL24x', ''.join([chr(x) for x in buf]))
        
        self.aUp = RingBuffer(arr[3:9])

        print 'WrOff=%d, RdOff=%d' %(self.aUp.WrOff, self.aUp.RdOff)
        
        self.aDown = RingBuffer(arr[9:15])
        
        return (self.aUp.RdOff == self.aUp.WrOff)
    
    def aUpRead(self):
        if self.aUp.RdOff < self.aUp.WrOff:
            len_ = self.aUp.WrOff - self.aUp.RdOff
            
            arr =  self.dap.read_memory_block8(self.aUp.pBuffer + self.aUp.RdOff, len_)
            
            self.aUp.RdOff += len_

            self.dap.write32(self.RTTAddr + (16 + 4*2) + 4*4, self.aUp.RdOff)
        else:
            len_ = self.aUp.SizeOfBuffer - self.aUp.RdOff + 1
            
            arr =  self.dap.read_memory_block8(self.aUp.pBuffer + self.aUp.RdOff, len_)
                        
            self.aUp.RdOff = 0  #这样下次再读就会进入执行上个条件
            
            self.dap.write32(self.RTTAddr + (16 + 4*2) + 4*4, self.aUp.RdOff)
        
        return ''.join([chr(x) for x in arr])
    
    def on_tmrRTT_timeout(self):
        if self.btnOpen.text() == u'关闭连接':
            try:
                if not self.aUpEmpty():
                    self.rcvbuff += self.aUpRead()

                    if self.txtMain.isVisible():
                        text = self.txtMain.toPlainText() + self.rcvbuff
                        if len(text) > 10000: text = text[5000:]
                        self.txtMain.setPlainText(text)
                        self.txtMain.moveCursor(QtGui.QTextCursor.End)
                        self.rcvbuff = b''

                    else:
                        if self.rcvbuff.rfind(',') == -1: return
                        
                        d = [int(x) for x in self.rcvbuff[0:self.rcvbuff.rfind(',')].split(',')]
                        for x in d:
                            self.PlotData.pop(0)
                            self.PlotData.append(x)
                        self.PlotCurve.setData(range(1, len(self.PlotData)+1), self.PlotData)
                        self.qwtPlot.replot() 
                        self.rcvbuff = self.rcvbuff[self.rcvbuff.rfind(',')+1:]
                        
            except Exception as e:
                self.rcvbuff = b''
                print e

        self.tmrRTT_Cnt += 1
        if self.tmrRTT_Cnt % 20 == 0:
            self.detect_daplink()   # 自动检测 DAPLink 的热插拔

    def detect_daplink(self):
        daplinks = aggregator.DebugProbeAggregator.get_all_connected_probes()
        
        if len(daplinks) != self.cmbDAP.count():
            self.cmbDAP.clear()
            for daplink in daplinks:
                self.cmbDAP.addItem(daplink.product_name)
        
            self.daplinks = collections.OrderedDict([(daplink.product_name, daplink) for daplink in daplinks])

            if self.daplink and self.daplink.product_name in self.daplinks:
                self.cmbDAP.setCurrentIndex(self.daplinks.keys().index(self.daplink.product_name))
            else:                                           # daplink被拔掉
                self.btnOpen.setText(u'打开连接')
                self.lblOpen.setPixmap(QtGui.QPixmap("./image/inclosing.png"))
            
    @QtCore.pyqtSlot(str)
    def on_cmbMode_currentIndexChanged(self, str):
        self.txtMain.setVisible(str == u'文本显示')
        self.qwtPlot.setVisible(str == u'波形显示')
    
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
