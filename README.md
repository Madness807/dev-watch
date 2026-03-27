# dev-watch

Dashboard web local pour surveiller et gerer les processus (Node.js, Python, Docker) qui tournent sur ta machine.

## Fonctionnalites

- **Vue en temps reel** des processus Node/Python et conteneurs Docker
- **Rafraichissement automatique** toutes les 5 secondes (+ bouton refresh manuel)
- **Filtres rapides** par type (Node / Python / Docker) en un clic
- **Filtre texte** par PID, nom de projet, port ou commande
- **Colonnes triables** (PID, projet, CPU, memoire)
- **Sparklines CPU/memoire** — mini graphiques d'historique par processus
- **Docker groupé par projet** compose avec accordeon et pastille de sante (vert/orange/rouge)
- **Kill / Stop / Restart** directement depuis l'interface
- **Notifications navigateur** quand un processus meurt ou un conteneur devient unhealthy
- **Tableau des ports** TCP en ecoute

## Architecture

| Fichier | Role |
|---------|------|
| `server.py` | Serveur Flask (port 3999) — scanne `/proc`, `ps aux` et Docker CLI, expose une API REST |
| `dev-watch.html` | Interface web standalone — consomme l'API et affiche le dashboard |
| `dev-watch.service` | Fichier systemd pour lancement automatique au boot (optionnel) |

## API

| Endpoint | Methode | Description |
|----------|---------|-------------|
| `/api/ps` | GET | Liste les processus Node/Python avec CPU, memoire, ports, repertoire, type |
| `/api/docker` | GET | Liste les conteneurs Docker avec status, health, projet compose, ports |
| `/api/kill` | POST | Tue un processus par PID (`{"pid": 1234}`) |
| `/api/docker/stop` | POST | Stoppe un conteneur (`{"id": "abc123"}`) |
| `/api/docker/restart` | POST | Redemarre un conteneur (`{"id": "abc123"}`) |
| `/api/health` | GET | Health check du serveur |

## Installation

```bash
# 1. Installer les dependances Python
pip install flask flask-cors --break-system-packages

# 2. Lancer le serveur
cd ~/dev-watch
python3 server.py

# 3. Ouvrir le dashboard dans le navigateur
xdg-open dev-watch.html
```

## Demarrage automatique (optionnel)

```bash
sudo cp dev-watch.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now dev-watch
sudo systemctl status dev-watch
```

## Prerequis

- Python 3
- Flask + flask-cors
- Linux (utilise `/proc` pour lire les infos processus)
- Docker (optionnel — le dashboard fonctionne sans)
