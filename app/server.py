import os, datetime
from flask import Flask, jsonify, request
import boto3
from botocore.exceptions import ClientError, NoCredentialsError

def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    # Région par défaut (prise depuis l'env si présente)
    app_state = {"region": os.getenv("AWS_DEFAULT_REGION", "eu-west-3")}

    # Helpers
    def session():
        # boto3 lit creds depuis env OU ~/.aws/credentials (profil default)
        return boto3.session.Session(region_name=app_state["region"])

    def ok(data): return jsonify({"success": True, "data": data})
    def err(msg, code=400): return jsonify({"success": False, "error": msg}), code

    # ---------- Health / Région ----------
    @app.get("/api/health")
    def health():
        try:
            sts = session().client("sts")
            ident = sts.get_caller_identity()
            return jsonify({"status": "ok",
                            "region": app_state["region"],
                            "account": ident.get("Account")})
        except NoCredentialsError:
            return err("Identifiants AWS introuvables (env ou ~/.aws).", 401)
        except ClientError as e:
            return err(str(e), 500)

    @app.put("/api/region")
    def put_region():
        body = request.get_json(silent=True) or {}
        region = body.get("region")
        if not region:
            return err("Champ 'region' requis", 400)
        app_state["region"] = region
        return ok({"region": region})

    # ---------- S3 ----------
    @app.get("/api/s3/buckets")
    def list_buckets():
        try:
            s3 = session().client("s3")
            res = s3.list_buckets()
            out = []
            for b in res.get("Buckets", []):
                name = b["Name"]
                # Région du bucket
                try:
                    loc = s3.get_bucket_location(Bucket=name).get("LocationConstraint")
                    region = loc or "us-east-1"
                except ClientError:
                    region = "unknown"
                # Versioning
                try:
                    ver = s3.get_bucket_versioning(Bucket=name).get("Status", "Disabled")
                except ClientError:
                    ver = "Unknown"
                out.append({
                    "name": name,
                    "region": region,
                    "creationDate": b["CreationDate"].astimezone(datetime.timezone.utc).isoformat(),
                    "versioning": ver
                })
            return ok(out)
        except ClientError as e:
            return err(e.response["Error"].get("Message", str(e)), 400)

    @app.post("/api/s3/buckets")
    def create_bucket():
        body = request.get_json(silent=True) or {}
        name = body.get("name")
        region = body.get("region") or app_state["region"]
        if not name:
            return err("Champ 'name' requis", 400)
        try:
            s3 = session().client("s3", region_name=region)
            if region == "us-east-1":
                s3.create_bucket(Bucket=name)
            else:
                s3.create_bucket(
                    Bucket=name,
                    CreateBucketConfiguration={"LocationConstraint": region}
                )
            return ok({"name": name})
        except ClientError as e:
            code = e.response["Error"].get("Code", "")
            msg = e.response["Error"].get("Message", str(e))
            if code in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
                return err("Nom de bucket indisponible. Choisis un nom globalement unique.", 409)
            if code == "InvalidBucketName":
                return err("Nom invalide (3–63, minuscules/chiffres/tirets).", 400)
            return err(msg, 400)

    # ---------- EC2 ----------
    @app.get("/api/ec2/instances")
    def list_instances():
        state = request.args.get("state", "").strip()
        name_like = request.args.get("name", "").strip().lower()
        try:
            ec2 = session().client("ec2")
            paginator = ec2.get_paginator("describe_instances")
            out = []
            for page in paginator.paginate():
                for r in page.get("Reservations", []):
                    for i in r.get("Instances", []):
                        st = i["State"]["Name"]
                        if state and st != state:
                            continue
                        tags = {t["Key"]: t["Value"] for t in i.get("Tags", [])} if i.get("Tags") else {}
                        name = tags.get("Name", "")
                        if name_like and name_like not in name.lower():
                            continue
                        out.append({
                            "id": i["InstanceId"],
                            "name": name or None,
                            "state": st,
                            "type": i.get("InstanceType"),
                            "az": i.get("Placement", {}).get("AvailabilityZone"),
                            "publicIp": i.get("PublicIpAddress"),
                            "launchTime": i["LaunchTime"].astimezone(datetime.timezone.utc).isoformat()
                        })
            out.sort(key=lambda x: x["launchTime"], reverse=True)
            return ok(out)
        except ClientError as e:
            return err(e.response["Error"].get("Message", str(e)), 400)

    @app.post("/api/ec2/instances")
    def run_instance():
        body = request.get_json(silent=True) or {}
        ami = body.get("ami")
        itype = body.get("type")
        key = body.get("keyName")
        sgs = body.get("securityGroupIds") or []
        if not all([ami, itype, key, sgs]):
            return err("Champs requis: ami, type, keyName, securityGroupIds[].", 400)
        try:
            ec2 = session().client("ec2")
            res = ec2.run_instances(
                ImageId=ami,
                InstanceType=itype,
                MinCount=1, MaxCount=1,
                KeyName=key,
                SecurityGroupIds=sgs,
                NetworkInterfaces=[{
                    "AssociatePublicIpAddress": True,
                    "DeviceIndex": 0,
                    "DeleteOnTermination": True
                }],
                TagSpecifications=[{
                    "ResourceType": "instance",
                    "Tags": [{"Key": "Project", "Value": "aws-portal"}]
                }]
            )
            iid = res["Instances"][0]["InstanceId"]
            return ok({"id": iid})
        except ClientError as e:
            return err(e.response["Error"].get("Message", str(e)), 400)

    # Page racine informative (UI statique servie par Nginx)
    @app.get("/")
    def root():
        return jsonify({"status": "running", "hint": "UI statique via Nginx, API sous /api/."})

    return app

if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=8000, debug=True)
