"""Operacje obejmujące wiele urządzeń: connect all, disconnect all i safe stop."""
class SystemControl:
    def __init__(self, tc200, mdt694b, mpc220, ads1263, logger) -> None:
        self.tc200 = tc200
        self.mdt694b = mdt694b
        self.mpc220 = mpc220
        self.ads1263 = ads1263
        self.logger = logger

    def connect_all(self) -> None: pass
    def disconnect_all(self) -> None: pass
    def safe_stop(self) -> None: pass
