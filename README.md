# DRTTView
SEGGER-RTT Client for DAPLink (CMSIS-DAP)

to run this software, you need python 3.6, pyqt5, pyqtchart, pyusb for CMSIS-DAPv2 and another usb-backend for CMSIS-DAPv1 (hidapi or pywinusb for windows, hidapi for mac, pyusb for linux)

wave show:
![](https://github.com/XIVN1987/RTTView/blob/master/截屏.gif)

data format for wave show: 
+ 1 wave: 11, 22, 33,
+ 2 wave: 11 22, 33 44, 55 66,
+ 3 wave: 11 22 33, 44 55 66, 77 88 99,
+ 4 wave: 11 22 33 44, 55 66 77 88, 99 11 22 33,

input:
![](https://github.com/XIVN1987/RTTView/blob/master/截屏.jpg)

Note: the software uses the following statement to find the debugger
``` python 
if product_name.find("CMSIS-DAP") < 0:
    # Skip non cmsis-dap HID device
```
