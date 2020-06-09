#! python3
import os
import sys
import ctypes
import collections
import configparser

from PyQt5 import QtCore, QtGui, uic
from PyQt5.QtCore import pyqtSlot, pyqtSignal, Qt, QThread
from PyQt5.QtWidgets import QApplication, QWidget, QMessageBox, QFileDialog
from PyQt5.QtChart import QChart, QChartView, QLineSeries

from pyocd.probe import aggregator
from pyocd.coresight import dap, ap, cortex_m


N_CURVES = 4

class RingBuffer(ctypes.Structure):
    _fields_ = [
        ('sName',        ctypes.c_uint),    # ctypes.POINTER(ctypes.c_char)，64位Python中 ctypes.POINTER 是64位的，与目标芯片不符
        ('pBuffer',      ctypes.c_uint),    # ctypes.POINTER(ctypes.c_byte)
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
class RTTView(QWidget, Ui_RTTView):
    def __init__(self, parent=None):
        super(RTTView, self).__init__(parent)
        
        self.setupUi(self)
'''
class RTTView(QWidget):
    def __init__(self, parent=None):
        super(RTTView, self).__init__(parent)
        
        uic.loadUi('RTTView.ui', self)

        self.initSetting()

        self.initQwtPlot()

        self.rcvbuff = ''

        self.daplink = None

        self.tmrRTT = QtCore.QTimer()
        self.tmrRTT.setInterval(10)
        self.tmrRTT.timeout.connect(self.on_tmrRTT_timeout)
        self.tmrRTT.start()

        self.tmrRTT_Cnt = 0
    
    def initSetting(self):
        if not os.path.exists('setting.ini'):
            open('setting.ini', 'w', encoding='utf-8')
        
        self.conf = configparser.ConfigParser()
        self.conf.read('setting.ini', encoding='utf-8')
        
        if not self.conf.has_section('Memory'):
            self.conf.add_section('Memory')
            self.conf.set('Memory', 'StartAddr', '0x20000000')

    def initQwtPlot(self):
        self.PlotData  = [[0]*1000 for i in range(N_CURVES)]
        self.PlotPoint = [[QtCore.QPointF(j, 0) for j in range(1000)] for i in range(N_CURVES)]

        self.PlotChart = QChart()

        self.ChartView = QChartView(self.PlotChart)
        self.ChartView.setVisible(False)
        self.vLayout.insertWidget(0, self.ChartView)
        
        self.PlotCurve = [QLineSeries() for i in range(N_CURVES)]
    
    @pyqtSlot()
    def on_btnOpen_clicked(self):
        if self.btnOpen.text() == u'打开连接':
            try:
                self.daplink = self.daplinks[self.cmbDAP.currentText()]
                self.daplink.open()
                
                _dp = dap.DebugPort(self.daplink, None)
                _dp.init()
                _dp.power_up_debug()

                _ap = ap.AHB_AP(_dp, 0)
                _ap.init()

                self.dap = cortex_m.CortexM(None, _ap)
                
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
                self.txtMain.append(f'\n{str(e)}\n')
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
                        text = ''.join(f'{ord(x):02X} ' for x in self.rcvbuff)
                    else:
                        text = self.rcvbuff

                    if len(self.txtMain.toPlainText()) > 25000: self.txtMain.clear()
                    self.txtMain.moveCursor(QtGui.QTextCursor.End)
                    self.txtMain.insertPlainText(text)

                    self.rcvbuff = ''

                else:
                    if self.rcvbuff.rfind(',') == -1: return
                    
                    d = self.rcvbuff[0:self.rcvbuff.rfind(',')].split(',')  # [b'12', b'34'] or [b'12 34', b'56 78']
                    d = [[float(x) for x in X.strip().split()] for X in d]  # [[12], [34]]   or [[12, 34], [56, 78]]
                    for arr in d:
                        for i, x in enumerate(arr):
                            if i == N_CURVES: break

                            self.PlotData[i].pop(0)
                            self.PlotData[i].append(x)
                            self.PlotPoint[i].pop(0)
                            self.PlotPoint[i].append(QtCore.QPointF(999, x))
                    
                    self.rcvbuff = self.rcvbuff[self.rcvbuff.rfind(',')+1:]

                    self.tmrRTT_Cnt += 1
                    if self.tmrRTT_Cnt % 4 == 0:
                        if len(d[-1]) != len(self.PlotChart.series()):
                            for series in self.PlotChart.series():
                                self.PlotChart.removeSeries(series)
                            for i in range(min(len(d[-1]), N_CURVES)):
                                self.PlotCurve[i].setName(f'Curve {i+1}')
                                self.PlotChart.addSeries(self.PlotCurve[i])
                            self.PlotChart.createDefaultAxes()

                        for i in range(len(self.PlotChart.series())):
                            for j, point in enumerate(self.PlotPoint[i]):
                                point.setX(j)
                        
                            self.PlotCurve[i].replace(self.PlotPoint[i])
                    
                        miny = min([min(d) for d in self.PlotData[:len(self.PlotChart.series())]])
                        maxy = max([max(d) for d in self.PlotData[:len(self.PlotChart.series())]])
                        self.PlotChart.axisY().setRange(miny, maxy)
                        self.PlotChart.axisX().setRange(0000, 1000)
                    
            except Exception as e:
                self.rcvbuff = ''
                print(str(e))   # 波形显示模式下 txtMain 不可见，因此错误信息不能显示在其上

        else:
            self.tmrRTT_Cnt += 1
            if self.tmrRTT_Cnt % 20 == 0:
                self.detect_daplink()   # 自动检测 DAPLink 的热插拔

    def aDownWrite(self, text):
        buf = self.dap.read_memory_block8(self.aDownAddr, ctypes.sizeof(RingBuffer))
        aDown = RingBuffer.from_buffer(bytearray(buf))
        
        if aDown.WrOff >= aDown.RdOff:
            if aDown.RdOff != 0: cnt = min(aDown.SizeOfBuffer - aDown.WrOff, len(text))
            else:                cnt = min(aDown.SizeOfBuffer - 1 - aDown.WrOff, len(text))    # 写入操作不能使得 aDown.WrOff == aDown.RdOff，以区分满和空
            self.dap.write_memory_block8(ctypes.cast(aDown.pBuffer, ctypes.c_void_p).value + aDown.WrOff, [ord(x) for x in text[:cnt]])
            
            aDown.WrOff += cnt
            if aDown.WrOff == aDown.SizeOfBuffer: aDown.WrOff = 0

            text = text[cnt:]

        if text and aDown.RdOff != 0 and aDown.RdOff != 1:         # != 0 确保 aDown.WrOff 折返回 0，!= 1 确保有空间可写入
            cnt = min(aDown.RdOff - 1 - aDown.WrOff, len(text))    # - 1 确保写入操作不导致WrOff与RdOff指向同一位置
            self.dap.write_memory_block8(ctypes.cast(aDown.pBuffer, ctypes.c_void_p).value + aDown.WrOff, [ord(x) for x in text[:cnt]])

            aDown.WrOff += cnt

        self.dap.write32(self.aDownAddr + 4*3, aDown.WrOff)

    @pyqtSlot()
    def on_btnSend_clicked(self):
        if self.btnOpen.text() == u'关闭连接':
            text = self.txtSend.toPlainText()

            try:
                if self.chkHEXSend.isChecked():
                    text = ''.join([chr(int(x, 16)) for x in text.split()])

                self.aDownWrite(text)

            except Exception as e:
                self.txtMain.append(f'\n{str(e)}\n')

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
            
    @pyqtSlot(int)
    def on_chkWavShow_stateChanged(self, state):
        self.ChartView.setVisible(state == Qt.Checked)
        self.txtMain.setVisible(state == Qt.Unchecked)
    
    @pyqtSlot()
    def on_btnClear_clicked(self):
        self.txtMain.clear()
    
    def closeEvent(self, evt):
        self.conf.write(open('setting.ini', 'w', encoding='utf-8'))


if __name__ == "__main__":
    app = QApplication(sys.argv)
    rtt = RTTView()
    rtt.show()
    app.exec()
