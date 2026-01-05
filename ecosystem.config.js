/**
 * PM2 Ecosystem Configuration
 * ===========================
 * Multi-bot deployment for Polymarket trading system
 *
 * Installation:
 *   npm install pm2 -g
 *
 * Usage:
 *   pm2 start ecosystem.config.js
 *   pm2 logs          # View all logs
 *   pm2 monit         # Real-time monitoring
 *   pm2 stop all      # Stop all bots
 *   pm2 restart all   # Restart all bots
 *   pm2 delete all    # Remove all processes
 */

module.exports = {
  apps: [
    // ========================================
    // Bot 1: ArbHunter (High-Frequency)
    // ========================================
    {
      name: "ArbHunter",
      script: "run_arbhunter.py",
      interpreter: "python3",

      // Performance settings
      instances: 1,
      exec_mode: "fork",  // Single process (WebSocket doesn't scale with cluster)

      // Auto-restart settings
      autorestart: true,
      watch: false,       // Don't watch files (too slow for HFT)
      max_memory_restart: "500M",  // Restart if memory exceeds 500MB

      // Restart strategy
      min_uptime: "10s",      // Must run 10s before considered stable
      max_restarts: 10,       // Max 10 restarts within...
      restart_delay: 5000,    // 5 seconds between restarts

      // Environment
      env: {
        NODE_ENV: "production",
        PYTHONUNBUFFERED: "1"  // Real-time logging
      },

      // Logging
      error_file: "logs/arbhunter-error.log",
      out_file: "logs/arbhunter-out.log",
      log_date_format: "YYYY-MM-DD HH:mm:ss Z",
      merge_logs: true,

      // Startup
      time: true
    },

    // ========================================
    // Bot 2: PolyAI (AI Analysis)
    // ========================================
    {
      name: "PolyAI",
      script: "run_polyai.py",
      interpreter: "python3",

      // Performance settings
      instances: 1,
      exec_mode: "fork",

      // Auto-restart settings
      autorestart: true,
      watch: false,
      max_memory_restart: "1G",  // AI uses more memory

      // Restart strategy
      min_uptime: "30s",
      max_restarts: 5,
      restart_delay: 10000,  // 10 seconds (AI initialization takes time)

      // Environment
      env: {
        NODE_ENV: "production",
        PYTHONUNBUFFERED: "1"
      },

      // Logging
      error_file: "logs/polyai-error.log",
      out_file: "logs/polyai-out.log",
      log_date_format: "YYYY-MM-DD HH:mm:ss Z",
      merge_logs: true,

      // Startup
      time: true
    },

    // ========================================
    // Bot 3: EliteMimic (Copy Trading)
    // ========================================
    {
      name: "EliteMimic",
      script: "run_elitemimic.py",
      interpreter: "python3",

      // Performance settings
      instances: 1,
      exec_mode: "fork",

      // Auto-restart settings
      autorestart: true,
      watch: false,
      max_memory_restart: "800M",

      // Restart strategy
      min_uptime: "20s",
      max_restarts: 8,
      restart_delay: 7000,

      // Environment
      env: {
        NODE_ENV: "production",
        PYTHONUNBUFFERED: "1"
      },

      // Logging
      error_file: "logs/elitemimic-error.log",
      out_file: "logs/elitemimic-out.log",
      log_date_format: "YYYY-MM-DD HH:mm:ss Z",
      merge_logs: true,

      // Startup
      time: true
    }
  ],

  /**
   * Deployment configuration (optional)
   * Use with: pm2 deploy ecosystem.config.js production setup
   */
  deploy: {
    production: {
      user: "ubuntu",
      host: "YOUR_SERVER_IP",
      ref: "origin/main",
      repo: "git@github.com:your-repo/polymarket-bot.git",
      path: "/home/ubuntu/polymarket-bot",
      "post-deploy": "pip install -r requirements.txt && pm2 reload ecosystem.config.js --env production"
    }
  }
};
