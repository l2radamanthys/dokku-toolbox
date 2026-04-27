# Dokku Toolbox 🧰

A secure web-based remote management tool for Dokku servers. Manage multiple apps and servers, execute pre-validated or custom commands, and maintain a full audit trail of all operations.

## ✨ Features

- **Multi-Server Management**: Register and monitor multiple Dokku instances via SSH.
- **App-Scoped Commands**: Execute commands across multiple apps or servers simultaneously.
- **Command Templates**: Define reusable, validated command templates to prevent shell injection.
- **Custom Commands**: One-off execution of arbitrary commands with safe character filtering.
- **SSH Key Management**: Store private keys securely (text or file path) and link them to servers.
- **Audit Logs**: Comprehensive, immutable execution logs with stdout, stderr, and exit codes.
- **Premium UI**: Modern dark-mode interface with glassmorphism aesthetics.
- **REST API**: Fully documented API for integration with other tools.

## 🚀 Quick Start

### Prerequisites
- Python 3.12+
- `uv` (recommended) or `pip`
- SSH access to your Dokku servers

### Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/youruser/dokku-toolbox.git
   cd dokku-toolbox
   ```

2. **Set up the environment**:
   ```bash
   uv venv
   source .venv/bin/activate
   uv sync
   ```

3. **Initialize the database**:
   ```bash
   python manage.py migrate
   python manage.py createsuperuser
   ```

4. **Run the development server**:
   ```bash
   python manage.py runserver 8001
   ```
   *Access the UI at `http://127.0.0.1:8001/ui/`*

## 🔒 Security

- **No Shell Expansion**: Uses Paramiko's `exec_command` directly, avoiding intermediate shell layers.
- **Command Sanitization**: All commands are validated against a strict allow-list of characters.
- **Audit Trail**: Every action is logged and associated with a user.
- **Isolated Authentication**: SSH keys can be stored separately and assigned per server.

## 🛠 Tech Stack

- **Backend**: Django 5.x, Django REST Framework
- **SSH Logic**: Paramiko
- **Database**: SQLite (default), PostgreSQL compatible
- **Styling**: Modern CSS3 (Glassmorphism, Dark Mode)
- **Deployment**: Dokku-ready!

## 📖 Usage

### Adding a Server
1. Go to **SSH Keys** and add your private key.
2. Go to **Servers** and add your Dokku host, selecting the key you just created.
3. Apps will be discovered automatically (or you can register them manually).

### Executing Commands
1. Navigate to **Execute Command**.
2. Choose a template (like `logs` or `ps:restart`) or type a custom command.
3. Select the target server and app.
4. View the results in real-time.

---

*Made with ❤️ for the Dokku community.*
