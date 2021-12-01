import os
import signal
import sys
import traceback
import threading
from typing import Optional, TYPE_CHECKING, List

try:
    import PyQt5
except Exception:
    sys.exit("Error: Could not import PyQt5 on Linux systems, you may try 'sudo apt-get install python3-pyqt5'")

try:
    import PyQt5.QtQml
except Exception:
    sys.exit("Error: Could not import PyQt5.QtQml on Linux systems, you may try 'sudo apt-get install python3-pyqt5.qtquick'")

from PyQt5.QtCore import pyqtProperty, pyqtSignal, pyqtSlot, QObject, QUrl, QLocale, QTimer, qInstallMessageHandler
from PyQt5.QtGui import QGuiApplication
from PyQt5.QtQml import qmlRegisterType, QQmlComponent, QQmlApplicationEngine
from PyQt5.QtQuick import QQuickView
import PyQt5.QtCore as QtCore
import PyQt5.QtQml as QtQml

from electrum.i18n import _, set_language, languages
from electrum.plugin import run_hook
from electrum.base_wizard import GoBack
from electrum.util import (UserCancelled, profiler,
                           WalletFileException, BitcoinException, get_new_wallet_name)
from electrum.wallet import Wallet, Abstract_Wallet
from electrum.wallet_db import WalletDB
from electrum.logging import Logger, get_logger

if TYPE_CHECKING:
    from electrum.daemon import Daemon
    from electrum.simple_config import SimpleConfig
    from electrum.plugin import Plugins

from .qeconfig import QEConfig
from .qedaemon import QEDaemon, QEWalletListModel
from .qenetwork import QENetwork
from .qewallet import QEWallet
from .qeqr import QEQR

class ElectrumQmlApplication(QGuiApplication):
    def __init__(self, args, config, daemon):
        super().__init__(args)

        self.logger = get_logger(__name__ + '.engine')

        qmlRegisterType(QEWalletListModel, 'org.electrum', 1, 0, 'WalletListModel')
        qmlRegisterType(QEWallet, 'org.electrum', 1, 0, 'Wallet')

        self.engine = QQmlApplicationEngine(parent=self)
        self.engine.addImportPath('./qml')

        self.context = self.engine.rootContext()
        self._singletons['config'] = QEConfig(config)
        self._singletons['network'] = QENetwork(daemon.network)
        self._singletons['daemon'] = QEDaemon(daemon)
        self._singletons['qr'] = QEQR()
        self.context.setContextProperty('Config', self._singletons['config'])
        self.context.setContextProperty('Network', self._singletons['network'])
        self.context.setContextProperty('Daemon', self._singletons['daemon'])
        self.context.setContextProperty('QR', self._singletons['qr'])

        qInstallMessageHandler(self.message_handler)

        # get notified whether root QML document loads or not
        self.engine.objectCreated.connect(self.objectCreated)

    _valid = True
    _singletons = {}

    # slot is called after loading root QML. If object is None, it has failed.
    @pyqtSlot('QObject*', 'QUrl')
    def objectCreated(self, object, url):
        if object is None:
            self._valid = False
        self.engine.objectCreated.disconnect(self.objectCreated)

    def message_handler(self, line, funct, file):
        self.logger.warning(file)

class ElectrumGui(Logger):

    @profiler
    def __init__(self, config: 'SimpleConfig', daemon: 'Daemon', plugins: 'Plugins'):
        set_language(config.get('language', self.get_default_language()))
        Logger.__init__(self)
        #os.environ['QML_IMPORT_TRACE'] = '1'
        #os.environ['QT_DEBUG_PLUGINS'] = '1'

        self.logger.info(f"Qml GUI starting up... Qt={QtCore.QT_VERSION_STR}, PyQt={QtCore.PYQT_VERSION_STR}")
        self.logger.info("CWD=%s" % os.getcwd())
        # Uncomment this call to verify objects are being properly
        # GC-ed when windows are closed
        #network.add_jobs([DebugMem([Abstract_Wallet, SPV, Synchronizer,
        #                            ElectrumWindow], interval=5)])
        QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_X11InitThreads)
        if hasattr(QtCore.Qt, "AA_ShareOpenGLContexts"):
            QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_ShareOpenGLContexts)
        if hasattr(QGuiApplication, 'setDesktopFileName'):
            QGuiApplication.setDesktopFileName('electrum.desktop')
        if hasattr(QtCore.Qt, "AA_EnableHighDpiScaling"):
            QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling);

        if not "QT_QUICK_CONTROLS_STYLE" in os.environ:
            os.environ["QT_QUICK_CONTROLS_STYLE"] = "Material"

        self.gui_thread = threading.current_thread()
        self.config = config
        self.daemon = daemon
        self.plugins = plugins
        self.app = ElectrumQmlApplication(sys.argv, self.config, self.daemon)
        # timer
        self.timer = QTimer(self.app)
        self.timer.setSingleShot(False)
        self.timer.setInterval(500)  # msec
        self.timer.timeout.connect(lambda: None) # periodically enter python scope

        # Initialize any QML plugins
        run_hook('init_qml', self)
        self.app.engine.load('electrum/gui/qml/components/main.qml')

    def close(self):
        self.app.quit()

    def main(self):
        if not self.app._valid:
            return

        self.timer.start()
        signal.signal(signal.SIGINT, lambda *args: self.stop())

        self.logger.info('Entering main loop')
        self.app.exec_()

    def stop(self):
        self.logger.info('closing GUI')
        self.app.quit()

    def get_default_language(self):
        name = QLocale.system().name()
        return name if name in languages else 'en_UK'

