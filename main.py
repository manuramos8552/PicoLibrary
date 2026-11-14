from kiosk_controller import KioskController

kiosk = KioskController()
try:
    kiosk.run()
except KeyboardInterrupt:
    kiosk.stop()
