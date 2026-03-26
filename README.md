# dev-watch

Dashboard web local pour surveiller et gérer les processus (Node.js, Python, Docker) qui tournent sur ta machine.

## Fonctionnalités

- **Vue en temps réel** des processus Node/Python/Docker (PID, projet, commande, CPU, mémoire, ports)
- **Rafraîchissement automatique** toutes les 3 secondes
- **Filtre** par PID, nom de projet, port ou commande
- **Kill de processus** directement depuis l'interface (SIGTERM)
- **Tableau des ports** TCP en écoute par les processus

## Architecture

| Fichier | Rôle |
|---------|------|
| `server.py` | Serveur Flask (port 3999) — scanne `/proc` et `ps aux`, expose une API REST |
| `dev-watch.html` | Interface web standalone — consomme l'API et affiche le dashboard |
| `dev-watch.service` | Fichier systemd pour lancement automatique au boot (optionnel) |

## API

| Endpoint | Méthode | Description |
|----------|---------|-------------|
| `/api/ps` | GET | Liste tous les processus (Node/Python/Docker) avec CPU, mémoire, ports, répertoire |
| `/api/kill` | POST | Tue un processus par PID (`{"pid": 1234}`) |
| `/api/health` | GET | Health check du serveur |

## Installation

```bash
# 1. Installer les dépendances Python
pip install flask flask-cors --break-system-packages

# 2. Lancer le serveur
cd ~/dev-watch
python3 server.py

# 3. Ouvrir le dashboard dans le navigateur
xdg-open dev-watch.html
```

## Démarrage automatique (optionnel)

```bash
# Adapter le username dans dev-watch.service si besoin, puis :
sudo cp dev-watch.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now dev-watch
sudo systemctl status dev-watch
```

## Prérequis

- Python 3
- Flask + flask-cors
- Linux (utilise `/proc` pour lire les infos processus)
