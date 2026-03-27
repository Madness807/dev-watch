# dev-watch

Dashboard web local pour surveiller et gerer les processus, conteneurs Docker, ports et connexions reseau sur ta machine de dev.

> **AVERTISSEMENT : Cet outil est concu UNIQUEMENT pour un usage local.**
> Il ne doit JAMAIS etre expose sur un reseau, un VPN, un reverse proxy, ou Internet.
> Il n'a pas d'authentification. Toute personne qui peut atteindre le port 3999
> peut voir vos processus et les tuer. Ne changez pas le bind `127.0.0.1` en `0.0.0.0`.

## Fonctionnalites

### Processus
- Detection automatique des processus **Node.js** et **Python** (hors containers Docker)
- Filtres rapides par type (Node / Python)
- Colonnes triables (type, PID, projet)
- Bouton kill (SIGTERM)

### Conteneurs Docker
- Groupes par projet compose avec accordeon
- Pastille de sante : vert (healthy), orange (unhealthy), rouge (down)
- Detection automatique de la tech via le nom du container (22 icones)
- Tag version sur les images : orange (latest), vert (version pinee)
- Ports bindes (host:container) vs ports internes
- Boutons restart / stop

### Reseau
- **Ports en ecoute (TCP)** : scan complet de la machine, pas juste Node/Python
- **Connexions actives (TCP)** : toutes les connexions ESTABLISHED avec processus et PID
- Indicateur de bind : vert (127.0.0.1) vs rouge (0.0.0.0)

### Systeme
- Barres de ressources dans la toolbar : CPU, RAM, disque, GPU (nvidia)
- Colorees selon l'usage (vert < 60%, jaune < 85%, rouge > 85%)

### Interface
- Sections en accordeon (ouvertes/fermees au clic)
- Toasts visuels in-page pour les evenements (processus termine, container unhealthy, etc.)
- Sons discrets (up/down) via Web Audio API
- Watch configurable : 3s / 5s / 10s / off
- Ligne de statut : verte clignotante (live) / rouge (watch off)
- Filtre texte global (PID, projet, port, type, commande)
- Bouton Disclaimer avec les regles de securite
- Zero appel reseau externe (icones locales, pas de CDN, pas de Google Fonts)

## Securite

Un bouton **Disclaimer** est accessible dans la toolbar du dashboard. Il resume les mesures de securite en place.

### Protections actives
- **Bind 127.0.0.1** : invisible depuis le reseau
- **CORS restreint** : localhost uniquement, pas de `null`, pas de `file://`
- **Allowlist PIDs** : seuls les processus scannes sont killables (403 sinon)
- **Allowlist containers** : seuls les containers scannes sont actionnables (403 sinon)
- **Pas de shell=True** : toutes les commandes via subprocess avec liste d'arguments
- **Echappement HTML** : protection XSS sur toutes les donnees dynamiques
- **Filtrage Docker** : les processus tournant dans des containers sont exclus de la section Processus
- **Dashboard servi par Flask** : pas de file://, meme origine

### Non protege (par design)
- Pas d'authentification (inutile sur 127.0.0.1)
- Pas de TLS (inutile en loopback)
- Pas de rate limiting (DoS local = tu te DoS toi-meme)
- Les commandes des processus peuvent contenir des secrets visibles dans le dashboard

## Architecture

| Fichier | Role |
|---------|------|
| `server.py` | Serveur Flask (port 3999) : API REST + sert le dashboard |
| `dev-watch.html` | Interface web : consomme l'API |
| `icons/` | 22 icones SVG locales (tech detection) |
| `start.sh` | Lance le serveur et ouvre le navigateur |
| `dev-watch.service` | Fichier systemd (optionnel) |

## API

| Endpoint | Methode | Description |
|----------|---------|-------------|
| `/` | GET | Dashboard HTML |
| `/api/ps` | GET | Processus Node/Python (hors containers) |
| `/api/docker` | GET | Conteneurs Docker (status, health, ports, projet compose) |
| `/api/ports` | GET | Tous les ports TCP en ecoute |
| `/api/connections` | GET | Connexions TCP actives (ESTABLISHED) |
| `/api/system` | GET | CPU, RAM, disque, GPU |
| `/api/docker/disk` | GET | Espace disque Docker |
| `/api/kill` | POST | Kill processus (`{"pid": 1234}`) — allowlist only |
| `/api/docker/stop` | POST | Stop container (`{"id": "abc123"}`) — allowlist only |
| `/api/docker/restart` | POST | Restart container (`{"id": "abc123"}`) — allowlist only |
| `/api/health` | GET | Health check |

## Installation

```bash
pip install flask flask-cors --break-system-packages
~/npm-watch/start.sh
```

## Prerequis

- Python 3
- Flask + flask-cors
- Linux (utilise `/proc` pour les infos processus)
- Docker (optionnel)
- nvidia-smi (optionnel, pour le GPU)
