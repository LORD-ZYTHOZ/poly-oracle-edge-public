module.exports = {
  apps: [
    {
      name: "poly-oracle-edge",
      script: "main.py",
      interpreter: "python3",
      env: {
        TRADING_MODE: "watch",
      },
      restart_delay: 5000,
      max_restarts: 10,
      log_file: "data/logs/pm2.log",
      error_file: "data/logs/pm2-error.log",
      out_file: "data/logs/pm2-out.log",
      time: true,
    },
  ],
};
