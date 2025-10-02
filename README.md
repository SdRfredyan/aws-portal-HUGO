AWS Portal — S3 & EC2 (MVP)

Mini-console web déployée sur EC2 qui permet :

S3

Lister les buckets (nom, région, date, versioning)

Créer un bucket dans une région donnée

EC2

Lister les instances (filtres par état et par tag Name)

Sélecteur de région (UI ⇄ API)

Pas d’upload S3 ni de lancement d’instance EC2 dans cette version.
Aucun rôle IAM à créer : on utilise tes identifiants fournis par aws configure sur l’EC2.

Structure du projet
aws-portal-/
├─ web/
│   └─ index.html          # UI (Bootstrap 5, fetch vers /api)
└─ app/
    ├─ server.py           # API Flask + boto3
    ├─ wsgi.py             # Entrée Gunicorn
    └─ requirements.txt    # flask, boto3, gunicorn

Prérequis

Instance EC2 Amazon Linux 2023 (t3.micro OK) avec IP publique

Security Group :

HTTP 80 : 0.0.0.0/0

SSH 22 : depuis ton IP

Paquets :

sudo yum update -y
sudo yum install -y nginx git python3-pip


Identifiants AWS sur l’instance (utilisateur ec2-user) :

aws configure
# saisis Access Key / Secret (et Session Token si Academy), et la région par défaut si tu veux


Les autorisations effectives (S3/EC2) proviennent de ces credentials.
Si une action échoue avec AccessDenied, c’est que les permissions de ces identifiants ne couvrent pas l’appel (voir Dépannage).

Installation (sur l’EC2)
# 1) Cloner le dépôt
sudo mkdir -p /opt/aws-portal && sudo chown ec2-user:ec2-user /opt/aws-portal
cd /opt/aws-portal
git clone <TON_REPO_GITHUB> aws-portal-
cd aws-portal-

# 2) Environnement Python pour l’API
python3 -m venv app/venv
source app/venv/bin/activate
pip install --upgrade pip
pip install -r app/requirements.txt
deactivate

Lancer l’API en service (systemd)

Créer /etc/systemd/system/aws-portal-api.service :

[Unit]
Description=AWS Portal API (Flask/Gunicorn)
After=network.target

[Service]
# Dossier qui contient wsgi.py
WorkingDirectory=/opt/aws-portal/aws-portal-/app
Environment=AWS_DEFAULT_REGION=eu-west-3
User=ec2-user
Group=ec2-user
ExecStart=/opt/aws-portal/aws-portal-/app/venv/bin/gunicorn -w 2 -b 127.0.0.1:8000 wsgi:app
Restart=on-failure

[Install]
WantedBy=multi-user.target


Puis :

sudo systemctl daemon-reload
sudo systemctl enable --now aws-portal-api
sudo systemctl status aws-portal-api --no-pager   # doit être "active (running)"
curl -s http://127.0.0.1:8000/api/health          # {"status":"ok","region":"...","account":"..."}

Servir l’UI + proxy /api avec Nginx

Déployer l’UI :

sudo mkdir -p /var/www/portal
sudo cp -a /opt/aws-portal/aws-portal-/web/* /var/www/portal/


Config /etc/nginx/conf.d/aws-portal.conf :

server {
    client_max_body_size 20m;

    listen 80;
    server_name _;

    root /var/www/portal;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    # proxy API -> Gunicorn
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}


Tester & recharger :

sudo nginx -t && sudo systemctl reload nginx

Utilisation

Ouvre http://<IP_PUBLIC_EC2>/

Dashboard : stats S3/EC2

S3 Buckets : liste + Créer un bucket

EC2 Instances : liste (filtres état / tag Name)

Change la région via le sélecteur (l’API suit et recharge les données).

Dépannage rapide

/api → 501 : le bloc /api de Nginx n’est pas en proxy (voir conf ci-dessus).

/api → 502/504 : service API down →
systemctl status aws-portal-api et journalctl -u aws-portal-api -n 100.

AccessDenied (S3/EC2) : les permissions de tes credentials aws configure ne couvrent pas l’opération.

Ex. pour lister S3 : il faut s3:ListAllMyBuckets.

Corrige côté compte qui t’a fourni les clés (ou change de credentials).

Région : passe à la région qui contient tes ressources (ex. us-east-1 en Academy) via le sélecteur, ou via PUT /api/region.

UI pas à jour : force refresh (Ctrl+F5) et redeploie l’index si modifié :

sudo cp -a /opt/aws-portal/aws-portal-/web/* /var/www/portal/
sudo systemctl reload nginx

Commandes utiles
# redéployer l’UI après un git pull
sudo cp -a /opt/aws-portal/aws-portal-/web/* /var/www/portal/
sudo systemctl reload nginx

# redémarrer l’API après modif Python
sudo systemctl restart aws-portal-api

# tester l’API
curl -s http://127.0.0.1:8000/api/health
curl -s http://<IP_PUBLIC>/api/health

Sécurité

Ne push jamais d’identifiants dans Git.

Les credentials sont fournis via aws configure sur l’EC2 et lus automatiquement par boto3.
