# DRTTView
SEGGER-RTT Client for DAPLink (CMSIS-DAP)

to run this software, you need python 3.6, pyqt5, pyqtchart and a usb backend (hidapi or pywinusb for windows, pyusb for linux, hidapi for mac)

wave show:
![](https://github.com/XIVN1987/RTTView/blob/master/截屏.gif)

input:
![](https://github.com/XIVN1987/RTTView/blob/master/截屏.jpg)

Note: the software uses the following statement to find the debugger
``` python 
if product_name.find("CMSIS-DAP") < 0:
    # Skip non cmsis-dap HID device
```
