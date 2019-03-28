#! python2
#coding: utf-8
import os
import sys
import ctypes
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


class RingBuffer(ctypes.Structure):
    _fields_ = [
        ('sName',        ctypes.POINTER(ctypes.c_char)),
        ('pBuffer',      ctypes.POINTER(ctypes.c_byte)),
        ('SizeOfBuffer', ctypes.c_uint),
        ('WrOff',        ctypes.c_uint),    # Position of next item to be written. 对于aUp：   芯片更新WrOff，主机更新RdOff
        ('RdOff',        ctypes.c_uint),    # Position of next item to be read.    对于aDown： 主机更新WrOff，芯片更新RdOff
        ('Flags',        ctypes.c_uint),
    ]

class SEGGER_RTT_CB(ctypes.Structure):      # Control Block
    _fields_ = [
        ('acID',              ctypes.c_char * 16),
        ('MaxNumUpBuffers',   ctypes.c_uint),
        ('MaxNumDownBuffers', ctypes.c_uint),
        ('aUp',               RingBuffer * 2),
        ('aDown',             RingBuffer * 2),
    ]


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

    def initQwtPlot(self):
        self.PlotData = [0]*1000
        
        self.qwtPlot = QwtPlot(self)
        self.qwtPlot.setVisible(False)
        self.vLayout.insertWidget(0, self.qwtPlot)
        
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
                
                Addr = int(self.conf.get('Memory', 'StartAddr'), 16)
                for i in range(256):
                    buff = self.dap.read_memory_block8(Addr + 1024*i, 1024)
                    buff = ''.join([chr(x) for x in buff])
                    index = buff.find('SEGGER RTT')
                    if index != -1:
                        self.RTTAddr = Addr + 1024*i + index

                        buff = self.dap.read_memory_block8(self.RTTAddr, ctypes.sizeof(SEGGER_RTT_CB))

                        rtt_cb = SEGGER_RTT_CB.from_buffer(bytearray(buff))
                        self.aUpAddr = self.RTTAddr + 16 + 4 + 4
                        self.aDownAddr = self.aUpAddr + ctypes.sizeof(RingBuffer) * rtt_cb.MaxNumUpBuffers

                        self.txtMain.append('\n_SEGGER_RTT @ 0x%08X with %d aUp and %d aDown\n' %(self.RTTAddr, rtt_cb.MaxNumUpBuffers, rtt_cb.MaxNumDownBuffers))
                        break
                else:
                    raise Exception('Can not find _SEGGER_RTT')
            except Exception as e:
                self.txtMain.append('\n%s\n' %str(e))
            else:
                self.cmbDAP.setEnabled(False)
                self.btnOpen.setText(u'关闭连接')
        else:
            self.daplink.close()
            self.cmbDAP.setEnabled(True)
            self.btnOpen.setText(u'打开连接')
    
    def aUpRead(self):
        buf = self.dap.read_memory_block8(self.aUpAddr, ctypes.sizeof(RingBuffer))
        aUp = RingBuffer.from_buffer(bytearray(buf))
        
        if aUp.RdOff == aUp.WrOff:
            buf = []

        elif aUp.RdOff < aUp.WrOff:
            cnt = aUp.WrOff - aUp.RdOff
            buf = self.dap.read_memory_block8(ctypes.cast(aUp.pBuffer, ctypes.c_void_p).value + aUp.RdOff, cnt)
            
            aUp.RdOff += cnt
            
            self.dap.write32(self.aUpAddr + 4*4, aUp.RdOff)

        else:
            cnt = aUp.SizeOfBuffer - aUp.RdOff
            buf = self.dap.read_memory_block8(ctypes.cast(aUp.pBuffer, ctypes.c_void_p).value + aUp.RdOff, cnt)
            
            aUp.RdOff = 0  #这样下次再读就会进入执行上个条件
            
            self.dap.write32(self.aUpAddr + 4*4, aUp.RdOff)
        
        return ''.join([chr(x) for x in buf])
    
    def on_tmrRTT_timeout(self):
        if self.btnOpen.text() == u'关闭连接':
            try:
                self.rcvbuff += self.aUpRead()

                if self.txtMain.isVisible():
                    if self.chkHEXShow.isChecked():
                        text = ''.join('%02X ' %ord(c) for c in self.rcvbuff)
                    else:
                        text = self.rcvbuff

                    if len(self.txtMain.toPlainText()) > 25000: self.txtMain.clear()
                    self.txtMain.moveCursor(QtGui.QTextCursor.End)
                    self.txtMain.insertPlainText(text)

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
                self.txtMain.append('\n%s\n' %str(e))

        else:
            self.tmrRTT_Cnt += 1
            if self.tmrRTT_Cnt % 20 == 0:
                self.detect_daplink()   # 自动检测 DAPLink 的热插拔

    def aDownWrite(self, bytes):
        buf = self.dap.read_memory_block8(self.aDownAddr, ctypes.sizeof(RingBuffer))
        aDown = RingBuffer.from_buffer(bytearray(buf))
        
        if aDown.WrOff >= aDown.RdOff:
            if aDown.RdOff != 0: cnt = min(aDown.SizeOfBuffer - aDown.WrOff, len(bytes))
            else:                cnt = min(aDown.SizeOfBuffer - 1 - aDown.WrOff, len(bytes))    # 写入操作不能使得 aDown.WrOff == aDown.RdOff，以区分满和空
            self.dap.write_memory_block8(ctypes.cast(aDown.pBuffer, ctypes.c_void_p).value + aDown.WrOff, [ord(x) for x in bytes[:cnt]])
            
            aDown.WrOff += cnt
            if aDown.WrOff == aDown.SizeOfBuffer: aDown.WrOff = 0

            bytes = bytes[cnt:]

        if bytes and aDown.RdOff != 0 and aDown.RdOff != 1:     # != 0 确保 aDown.WrOff 折返回 0，!= 1 确保有空间可写入
            cnt = min(aDown.RdOff - 1 - aDown.WrOff, len(bytes))    # - 1 确保写入操作不导致WrOff与RdOff指向同一位置
            self.dap.write_memory_block8(ctypes.cast(aDown.pBuffer, ctypes.c_void_p).value + aDown.WrOff, [ord(x) for x in bytes[:cnt]])

            aDown.WrOff += cnt

        self.dap.write32(self.aDownAddr + 4*3, aDown.WrOff)

    @QtCore.pyqtSlot()
    def on_btnSend_clicked(self):
        if self.btnOpen.text() == u'关闭连接':
            text = self.txtSend.toPlainText()

            try:
                if self.chkHEXSend.isChecked():
                    bytes = ''.join([chr(int(x, 16)) for x in text.split()])

                else:
                    bytes = text

                self.aDownWrite(bytes)

            except Exception as e:
                self.txtMain.append('\n%s\n' %str(e))

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
            
    @QtCore.pyqtSlot(int)
    def on_chkWavShow_stateChanged(self, state):
        self.qwtPlot.setVisible(state == QtCore.Qt.Checked)
        self.txtMain.setVisible(state == QtCore.Qt.Unchecked)
    
    @QtCore.pyqtSlot()
    def on_btnClear_clicked(self):
        self.txtMain.clear()
    
    def closeEvent(self, evt):
        self.conf.write(open('setting.ini', 'w'))


if __name__ == "__main__":
    app = QtGui.QApplication(sys.argv)
    rtt = RTTView()
    rtt.show()
    app.exec_()
