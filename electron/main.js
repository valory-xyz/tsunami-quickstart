const dotenv = require('dotenv');

const {
  app,
  BrowserWindow,
  Tray,
  Menu,
  Notification,
  ipcMain,
} = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const os = require('os');
const next = require('next');
const http = require('http');
const { TRAY_ICONS, TRAY_ICONS_PATHS } = require('./icons');

const {
  setupDarwin,
  setupUbuntu,
  OperateCmd,
  OperateDirectory,
  startDocker,
  Env,
} = require('./install');
const { killProcesses } = require('./processes');
const { isPortAvailable, findAvailablePort } = require('./ports');
const { PORT_RANGE, isWindows, isMac } = require('./constants');

// Configure environment variables
dotenv.config();

// Attempt to acquire the single instance lock
const singleInstanceLock = app.requestSingleInstanceLock();
if (!singleInstanceLock) app.quit();

const platform = os.platform();
const isDev = process.env.NODE_ENV === 'development';
let appConfig = {
  ports: {
    dev: {
      operate: 8000,
      next: 3000,
    },
    prod: {
      operate: 8000,
      next: 3000,
    },
  },
};

let tray,
  mainWindow,
  splashWindow,
  operateDaemon,
  operateDaemonPid,
  nextAppProcess,
  nextAppProcessPid;

async function beforeQuit() {
  if (operateDaemonPid) {
    try {
      await killProcesses(operateDaemonPid);
    } catch (e) {
      console.error(e);
    }
  }

  if (nextAppProcessPid) {
    try {
      await killProcesses(nextAppProcessPid);
    } catch (e) {
      console.error(e);
    }
  }

  tray && tray.destroy();
  mainWindow && mainWindow.destroy();
}

/**
 * Creates the tray
 */
const createTray = () => {
  const trayPath =
    isWindows || isMac ? TRAY_ICONS.LOGGED_OUT : TRAY_ICONS_PATHS.LOGGED_OUT;
  const trayIcon = trayPath.resize({ width: 16 });
  trayIcon.setTemplateImage(true);
  const tray = new Tray(trayIcon);

  const contextMenu = Menu.buildFromTemplate([
    {
      label: 'Show app',
      click: function () {
        mainWindow.show();
      },
    },
    {
      label: 'Hide app',
      click: function () {
        mainWindow.hide();
      },
    },
    {
      label: 'Quit',
      click: async function () {
        await beforeQuit();
        app.quit();
      },
    },
  ]);
  tray.setToolTip('Olas Operate');
  tray.setContextMenu(contextMenu);
  tray.on('click', () => {
    mainWindow.show();
  });

  ipcMain.on('tray', (_event, status) => {
    switch (status) {
      case 'low-gas':
        tray.setImage(
          isWindows || isMac ? TRAY_ICONS.LOW_GAS : TRAY_ICONS_PATHS.LOW_GAS,
        );
        break;
      case 'running':
        tray.setImage(
          isWindows || isMac ? TRAY_ICONS.RUNNING : TRAY_ICONS_PATHS.RUNNING,
        );
        break;
      case 'paused':
        tray.setImage(
          isWindows || isMac ? TRAY_ICONS.PAUSED : TRAY_ICONS_PATHS.PAUSED,
        );
        break;
    }
  });

  ipcMain.on('close-app', () => {
    const currentWindow = BrowserWindow.getFocusedWindow();
    if (currentWindow) {
      currentWindow.close();
    }
  });

  ipcMain.on('minimize-app', () => {
    const currentWindow = BrowserWindow.getFocusedWindow();
    if (currentWindow) {
      currentWindow.minimize();
    }
  });
};

/**
 * Creates the splash window
 */
const createSplashWindow = () => {
  splashWindow = new BrowserWindow({
    width: 420,
    height: 420,
    resizable: false,
    show: true,
    title: 'Olas Operate',
    frame: false,
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false,
    },
  });
  splashWindow.loadURL('file://' + __dirname + '/loading/index.html');
  // if (isDev) {
  //   splashWindow.webContents.openDevTools();
  // }
};

/**
 * Creates the main window
 */
const createMainWindow = () => {
  mainWindow = new BrowserWindow({
    title: 'Olas Operate',
    resizable: false,
    draggable: true,
    frame: true,
    transparent: true,
    fullscreenable: false,
    maximizable: false,
    // width: 420,
    width: isDev ? 840 : 420,
    height: 735,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js'),
    },
  });

  mainWindow.setMenuBarVisibility(false);

  if (isDev) {
    mainWindow.loadURL(`http://localhost:${appConfig.ports.dev.next}`);
  } else {
    mainWindow.loadURL(`http://localhost:${appConfig.ports.prod.next}`);
  }

  mainWindow.webContents.on('did-fail-load', () => {
    mainWindow.webContents.reloadIgnoringCache();
  });

  mainWindow.webContents.on('ready-to-show', () => {
    mainWindow.show();
  });

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    // open url in a browser and prevent default
    require('electron').shell.openExternal(url);
    return { action: 'deny' };
  });

  // console.log('mainWindow.webContents', mainWindow.webContents);

  // mainWindow.webContents.on('did-navigate-in-page', () => {
  //   const contentSize = mainWindow.getContentSize();
  //   const [width, height] = contentSize;
  //   console.log(width, height);
  //   // mainWindow.setSize(width, height + 50); // Add some extra height for padding, if needed
  // });

  mainWindow.on('close', function (event) {
    event.preventDefault();
    mainWindow.hide();
  });

  if (isDev) {
    mainWindow.webContents.openDevTools();
  }
};

async function launchDaemon() {
  function appendLog(data) {
    fs.appendFileSync(`${OperateDirectory}/logs.txt`, data.trim() + '\n', {
      encoding: 'utf-8',
    });
    return data;
  }
  const check = new Promise(function (resolve, _reject) {
    operateDaemon = spawn(
      OperateCmd,
      [
        'daemon',
        `--port=${appConfig.ports.prod.operate}`,
        `--home=${OperateDirectory}`,
      ],
      { env: Env },
    );
    operateDaemonPid = operateDaemon.pid;
    operateDaemon.stderr.on('data', (data) => {
      if (data.toString().includes('Uvicorn running on')) {
        resolve({ running: true, error: null });
      }
      if (
        data.toString().includes('error while attempting to bind on address')
      ) {
        resolve({ running: false, error: 'Port already in use' });
      }
      console.log(appendLog(data.toString().trim()));
    });
    operateDaemon.stdout.on('data', (data) => {
      console.log(appendLog(data.toString().trim()));
    });
  });
  return await check;
}

async function launchDaemonDev() {
  const check = new Promise(function (resolve, _reject) {
    operateDaemon = spawn('poetry', [
      'run',
      'operate',
      'daemon',
      `--port=${appConfig.ports.dev.operate}`,
      '--home=.operate',
    ]);
    operateDaemonPid = operateDaemon.pid;
    operateDaemon.stderr.on('data', (data) => {
      if (data.toString().includes('Uvicorn running on')) {
        resolve({ running: true, error: null });
      }
      if (
        data.toString().includes('error while attempting to bind on address')
      ) {
        resolve({ running: false, error: 'Port already in use' });
      }
      console.log(data.toString().trim());
    });
    operateDaemon.stdout.on('data', (data) => {
      console.log(data.toString().trim());
    });
  });
  return await check;
}

async function launchNextApp() {
  const nextApp = next({
    dev: false,
    dir: path.join(__dirname),
    port: appConfig.ports.prod.next,
    env: {
      GNOSIS_RPC:
        process.env.NODE_ENV === 'production'
          ? process.env.FORK_URL
          : process.env.DEV_RPC,
    },
  });
  await nextApp.prepare();

  const handle = nextApp.getRequestHandler();
  const server = http.createServer((req, res) => {
    handle(req, res); // Handle requests using the Next.js request handler
  });
  server.listen(appConfig.ports.prod.next, (err) => {
    if (err) throw err;
    console.log(
      `> Next server running on http://localhost:${appConfig.ports.prod.next}`,
    );
  });
}

async function launchNextAppDev() {
  await new Promise(function (resolve, _reject) {
    process.env.NEXT_PUBLIC_BACKEND_PORT = appConfig.ports.dev.operate; // must set next env var to connect to backend
    nextAppProcess = spawn(
      'yarn',
      ['dev:frontend', '--port', appConfig.ports.dev.next],
      {
        env: { ...process.env },
      },
    );
    nextAppProcessPid = nextAppProcess.pid;
    nextAppProcess.stdout.on('data', (data) => {
      console.log(data.toString().trim());
      resolve();
    });
  });
}

ipcMain.on('check', async function (event, _argument) {
  try {
    event.sender.send('response', 'Checking installation');
    if (!isDev) {
      if (platform === 'darwin') {
        await setupDarwin(event.sender);
      } else if (platform === 'win32') {
        // TODO
      } else {
        await setupUbuntu(event.sender);
      }
    }

    startDocker(event.sender);

    if (isDev) {
      event.sender.send(
        'response',
        'Starting Operate Daemon In Development Mode',
      );

      const daemonDevPortAvailable = await isPortAvailable(
        appConfig.ports.dev.operate,
      );

      if (!daemonDevPortAvailable) {
        appConfig.ports.dev.operate = await findAvailablePort({
          ...PORT_RANGE,
        });
      }
      await launchDaemonDev();
      event.sender.send(
        'response',
        'Starting Frontend Server In Development Mode',
      );

      const frontendDevPortAvailable = await isPortAvailable(
        appConfig.ports.dev.next,
      );

      if (!frontendDevPortAvailable) {
        appConfig.ports.dev.next = await findAvailablePort({
          ...PORT_RANGE,
          excludePorts: [appConfig.ports.dev.operate],
        });
      }
      await launchNextAppDev();
    } else {
      event.sender.send('response', 'Starting Operate Daemon');
      const daemonPortAvailable = await isPortAvailable(
        appConfig.ports.prod.operate,
      );
      if (!daemonPortAvailable) {
        appConfig.ports.prod.operate = await findAvailablePort({
          ...PORT_RANGE,
        });
      }
      await launchDaemon();
      event.sender.send('response', 'Starting Frontend Server');
      const frontendPortAvailable = await isPortAvailable(
        appConfig.ports.prod.next,
      );
      if (!frontendPortAvailable) {
        appConfig.ports.prod.next = await findAvailablePort({
          ...PORT_RANGE,
          excludePorts: [appConfig.ports.prod.operate],
        });
      }
      await launchNextApp();
    }

    event.sender.send('response', 'Launching App');
    createMainWindow();
    createTray();
    splashWindow.destroy();
  } catch (e) {
    console.log(e);
    new Notification({
      title: 'Error',
      body: e,
    }).show();
    event.sender.send('response', e);
    // app.quit();
  }
});

// APP-SPECIFIC EVENTS
app.on('ready', async () => {
  if (platform === 'darwin') {
    app.dock?.setIcon(
      path.join(__dirname, 'assets/icons/splash-robot-head-dock.png'),
    );
  }
  createSplashWindow();
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('before-quit', () => {
  beforeQuit();
});

// PROCESS SPECIFIC EVENTS (HANDLES NON-GRACEFUL TERMINATION)

process.on('uncaughtException', (error) => {
  console.error('Uncaught Exception:', error);
  // Clean up your child processes here
  beforeQuit().then(() => {
    process.exit(1); // Exit with a failure code
  });
});

['SIGINT', 'SIGTERM'].forEach((signal) => {
  process.on(signal, () => {
    console.log(`Received ${signal}. Cleaning up...`);
    beforeQuit().then(() => {
      process.exit(0);
    });
  });
});
