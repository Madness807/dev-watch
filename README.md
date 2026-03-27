# dev-watch

Dashboard web local pour surveiller et gerer les processus (Node.js, Python, Docker) qui tournent sur ta machine.

> **AVERTISSEMENT : Cet outil est concu UNIQUEMENT pour un usage local.**
> Il ne doit JAMAIS etre expose sur un reseau, un VPN, un reverse proxy, ou Internet.
> Il n'a pas d'authentification. Toute personne qui peut atteindre le port 3999
> peut voir vos processus et les tuer. Ne changez pas le bind `127.0.0.1` en `0.0.0.0`.

## Fonctionnalites

- **Vue en temps reel** des processus Node/Python et conteneurs Docker
- **Rafraichissement automatique** toutes les 5 secondes (+ bouton refresh manuel)
- **Filtres rapides** par type (Node / Python / Docker) en un clic
- **Filtre texte** par PID, nom de projet, port ou commande
- **Colonnes triables** (PID, projet, CPU, memoire, type)
- **Sparklines CPU/memoire** — mini graphiques d'historique par processus
- **Docker groupe par projet** compose avec accordeon et pastille de sante (vert/orange/rouge)
- **Kill / Stop / Restart** directement depuis l'interface
- **Notifications navigateur** quand un processus meurt ou un conteneur devient unhealthy
- **Tableau des ports** TCP en ecoute

## Securite

Cet outil a ete audite et durci pour un usage local. Voici les mesures en place :

### Reseau

- **Bind `127.0.0.1` uniquement** — le serveur n'ecoute que sur localhost, il est invisible depuis le reseau
- **CORS restreint** — seules les origines `http://localhost` et `http://127.0.0.1` sont acceptees. Les requetes depuis `file://`, `data:`, ou tout autre site sont rejetees
- **Dashboard servi par Flask** — le HTML est servi sur `http://localhost:3999/`, pas ouvert en `file://`, ce qui evite les problemes de CORS et les attaques par fichier HTML malicieux

### Actions destructives

- **Allowlist de PIDs** — seuls les processus detectes par le dernier scan `/api/ps` peuvent etre tues. Un PID arbitraire est rejete avec une erreur 403
- **Allowlist de containers Docker** — seuls les containers detectes par le dernier scan `/api/docker` peuvent etre stoppes ou redemarres. Un ID inconnu est rejete
- **PID 1 et self protege** — le serveur refuse de se tuer lui-meme ou de toucher au PID 1

### Code

- **Pas de `shell=True`** — toutes les commandes systeme utilisent `subprocess` avec des listes d'arguments, pas d'interpretation shell
- **Validation regex** sur les IDs de containers Docker avant toute action
- **Echappement HTML (XSS)** — toutes les donnees dynamiques (nom de projet, commande, repertoire) sont echappees avant injection dans le DOM
- **Gestion gracieuse de Docker absent** — si Docker n'est pas installe ou si le daemon ne tourne pas, l'API retourne un tableau vide sans erreur

### Ce que cet outil ne fait PAS

- Pas d'authentification (token, mot de passe) — inutile en local sur `127.0.0.1`
- Pas de chiffrement TLS — inutile en loopback
- Pas de rate limiting — un DoS local n'a pas de sens (tu te DoS toi-meme)
- Pas de serveur WSGI production (gunicorn) — c'est un outil de dev, pas un service expose

Ces choix sont **volontaires**. Ajouter ces couches pour un outil local serait de la sur-ingenierie. Si vous avez besoin d'exposer ce dashboard sur un reseau, **ne le faites pas**. Ecrivez un autre outil avec une architecture adaptee.

## Architecture

| Fichier | Role |
|---------|------|
| `server.py` | Serveur Flask (port 3999) — scanne `/proc`, `ps aux` et Docker CLI, expose une API REST + sert le dashboard |
| `dev-watch.html` | Interface web — consomme l'API et affiche le dashboard |
| `dev-watch.service` | Fichier systemd pour lancement automatique au boot (optionnel) |
| `start.sh` | Script de lancement — demarre le serveur et ouvre le navigateur |

## API

| Endpoint | Methode | Description |
|----------|---------|-------------|
| `/` | GET | Sert le dashboard HTML |
| `/api/ps` | GET | Liste les processus Node/Python avec CPU, memoire, ports, repertoire, type |
| `/api/docker` | GET | Liste les conteneurs Docker avec status, health, projet compose, ports |
| `/api/kill` | POST | Tue un processus par PID (`{"pid": 1234}`) — uniquement les PIDs connus |
| `/api/docker/stop` | POST | Stoppe un conteneur (`{"id": "abc123"}`) — uniquement les IDs connus |
| `/api/docker/restart` | POST | Redemarre un conteneur (`{"id": "abc123"}`) — uniquement les IDs connus |
| `/api/health` | GET | Health check du serveur |

## Installation

```bash
# 1. Installer les dependances Python
pip install flask flask-cors --break-system-packages

# 2. Lancer
~/dev-watch/start.sh
```

Le script demarre le serveur et ouvre `http://localhost:3999` dans le navigateur. `Ctrl+C` pour arreter.

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
