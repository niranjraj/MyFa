"""Upload the MyFA addon (not the desktop app) to CurseForge.

Needs, in the GitHub repo settings (Settings > Secrets and variables > Actions):
  secret   CF_API_TOKEN      from https://legacy.curseforge.com/account/api-tokens
  variable CF_PROJECT_ID     the Project ID shown in the "About Project" box on your CurseForge page
  variable CF_GAME_VERSIONS  optional: game version names or IDs, comma-separated, if the automatic pick is wrong

Without the token or project ID it skips quietly, so releases keep working.
"""
import json
import os
import pathlib
import re
import sys
import urllib.error
import urllib.request
import uuid
import zipfile

API = "https://wow.curseforge.com/api"
ROOT = pathlib.Path(__file__).resolve().parents[2]


def get(path, token):
    req = urllib.request.Request(API + path, headers={"X-Api-Token": token, "User-Agent": "MyFA-release"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def pick_versions(types, versions, wanted=""):
    """Game version IDs to tag the file with: the ones named in CF_GAME_VERSIONS, else the newest WoW Forever version."""
    wanted = [w.strip() for w in (wanted or "").split(",") if w.strip()]
    if wanted:
        out = []
        for w in wanted:
            if w.isdigit():
                out.append(int(w))
                continue
            match = [v["id"] for v in versions if v.get("name") == w or v.get("slug") == w]
            if not match:
                raise SystemExit(f"CF_GAME_VERSIONS: no CurseForge game version called {w!r}.")
            out.append(max(match))
        return out
    forever = {t["id"] for t in types if "forever" in (str(t.get("name", "")) + " " + str(t.get("slug", ""))).lower()}
    candidates = [v for v in versions if v.get("gameVersionTypeID") in forever]
    if not candidates:
        names = ", ".join(sorted({str(t.get("name")) for t in types}))
        raise SystemExit("Couldn't find a WoW Forever game version on CurseForge. Set the CF_GAME_VERSIONS repository "
                         f"variable to the right version name. Version types CurseForge offers: {names}")
    return [max(candidates, key=lambda v: v["id"])["id"]]


def changelog_for(version):
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    m = re.search(rf"^## {re.escape(version)}\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    return (m.group(1).strip() if m else f"MyFA {version}") + (
        "\n\nMyFA Desk, the free desktop app that turns your scans into targets, is on GitHub: "
        "https://github.com/niranjraj/MyFa/releases/latest")


def build_zip(version, project_id):
    """The addon folder only, its .toc stamped so MyFA Desk knows the CurseForge app keeps it up to date."""
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    out = dist / f"MyFA-v{version}-curseforge.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted((ROOT / "MyFA").rglob("*")):
            if f.is_dir():
                continue
            arc = "MyFA/" + f.relative_to(ROOT / "MyFA").as_posix()
            if f.name == "MyFA.toc":
                toc = f.read_text(encoding="utf-8")
                toc = re.sub(r"^## Version: .*$", f"## Version: {version}", toc, flags=re.M)
                extra = f"## X-Curse-Project-ID: {project_id}\n## X-MyFA-Source: curseforge\n"
                toc = toc.replace("## SavedVariables:", extra + "## SavedVariables:", 1)
                z.writestr(arc, toc)
            else:
                z.write(f, arc)
    return out


def upload(path, metadata, project_id, token):
    boundary = uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"metadata\"\r\n\r\n{json.dumps(metadata)}\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{path.name}\"\r\n"
            "Content-Type: application/zip\r\n\r\n").encode() + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(f"{API}/projects/{project_id}/upload-file", data=body, method="POST", headers={
        "X-Api-Token": token, "Content-Type": f"multipart/form-data; boundary={boundary}", "User-Agent": "MyFA-release"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        raise SystemExit(f"CurseForge refused the upload ({e.code}): {e.read().decode('utf-8', 'replace')[:500]}")


def main():
    token = os.environ.get("CF_API_TOKEN", "").strip()
    project_id = os.environ.get("CF_PROJECT_ID", "").strip()
    if not token or not project_id:
        print("::notice::CurseForge upload skipped: add the CF_API_TOKEN secret and CF_PROJECT_ID variable to turn it on.")
        return
    version = (ROOT / "MyFA-Desk" / "VERSION").read_text().strip()
    zip_path = build_zip(version, project_id)
    ids = pick_versions(get("/game/version-types", token), get("/game/versions", token), os.environ.get("CF_GAME_VERSIONS", ""))
    meta = {"changelog": changelog_for(version), "changelogType": "markdown", "displayName": f"MyFA v{version}",
            "gameVersions": ids, "releaseType": os.environ.get("CF_RELEASE_TYPE", "release") or "release"}
    res = upload(zip_path, meta, project_id, token)
    print(f"Uploaded {zip_path.name} to CurseForge project {project_id} (file {res.get('id')}, game versions {ids}).")


if __name__ == "__main__":
    sys.exit(main())
