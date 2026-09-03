#!/usr/bin/env python3
"""Minimal DSG installer CLI for the same provisioner used by the web UI."""
import argparse, json, os, sys, urllib.request

BASE=os.environ.get("DSG_PRODUCT_URL","http://127.0.0.1:8000").rstrip("/")
KEY=os.environ.get("DSG_API_KEY","")

def call(path, method="GET", body=None):
    data=None if body is None else json.dumps(body).encode()
    headers={"Accept":"application/json"}
    if data: headers["Content-Type"]="application/json"
    if KEY: headers["X-DSG-API-Key"]=KEY
    req=urllib.request.Request(BASE+path,data=data,headers=headers,method=method)
    with urllib.request.urlopen(req,timeout=30) as r:
        return json.loads(r.read())

p=argparse.ArgumentParser(prog="dsgctl")
sub=p.add_subparsers(dest="cmd",required=True)
i=sub.add_parser("install"); i.add_argument("target"); i.add_argument("--integration",choices=["mcp","github","api"],default="github"); i.add_argument("--scope",default="selected-repository")
s=sub.add_parser("status"); s.add_argument("installation_id")
d=sub.add_parser("doctor"); d.add_argument("installation_id")
f=sub.add_parser("first-result"); f.add_argument("installation_id")
args=p.parse_args()
if args.cmd=="install": out=call("/platform/install/start","POST",{"target_id":args.target,"integration":args.integration,"install_path":"cli","scope":args.scope,"permissions":["metadata:read","contents:read","actions:write"]})
elif args.cmd=="status": out=call(f"/platform/install/{args.installation_id}")
elif args.cmd=="doctor": out=call(f"/platform/install/{args.installation_id}/doctor","POST",{})
else: out=call(f"/platform/install/{args.installation_id}/first-result","POST",{})
print(json.dumps(out,ensure_ascii=False,indent=2))
