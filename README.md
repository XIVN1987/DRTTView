# RTTView
SEGGER-RTT Terminal program using CMSIS-DAP (DAPLink)

to run this software, you need python 2.7, pyqt4, pyqwt5, enum34 and a usb backend (hidapi or pywinusb for windows, pyusb for linux, hidapi for mac)

![](https://github.com/XIVN1987/RTTView/blob/master/RTTView.png)
Note: the software uses the following statement to find the debugger
``` python 
if product_name.find("CMSIS-DAP") < 0:
    # Skip non cmsis-dap HID device
```
