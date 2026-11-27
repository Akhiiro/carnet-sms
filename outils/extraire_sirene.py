"""
Extrait une liste d'artisans depuis l'API publique Recherche d'entreprises (gratuite, sans clé).
Source : https://recherche-entreprises.api.gouv.fr (données SIRENE + dirigeants du RNE).

Usage (sur ton PC, Python 3, aucune librairie à installer) :
    python extraire_sirene.py --naf 43.22A,43.22B,43.21A,43.91B --rayon 40
Sortie : prospects_villefranche.csv, prêt à coller dans l'onglet Prospects du tableur.

Le mobile n'existe pas dans SIRENE : il faut le relever à la main sur la fiche Google Maps,
Pages Jaunes ou le site de l'entreprise (06/07 publié par l'entreprise uniquement).
"""
import argparse, csv, json, math, time, urllib.parse, urllib.request
from datetime import date

VILLEFRANCHE = (45.9895, 4.7186)
# Vraies entreprises : SARL/EURL (54xx), SA (55xx), SAS/SASU (57xx). On exclut l'entreprise individuelle et la micro (1000).
FORMES_OK = ("54", "55", "57")

API = "https://recherche-entreprises.api.gouv.fr/search"
# Tranches d'effectif : 01 = 1-2 salariés, 02 = 3-5, 03 = 6-9, 11 = 10-19
TRANCHES_CIBLES = {"01": "1-2", "02": "3-5", "03": "6-9", "11": "10-19"}
SCORE_TRANCHE = {"01": 3, "02": 3, "03": 2, "11": 1}


def appel(params):
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "prospection-artisans/1.0"})
    for essai in range(4):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.load(r)
        except Exception as e:  # 429 = trop de requêtes : on attend
            time.sleep(2 * (essai + 1))
    raise SystemExit(f"API injoignable : {url}")


def gerant(e):
    for d in e.get("dirigeants") or []:
        if d.get("type_dirigeant") == "personne physique":
            prenom = (d.get("prenoms") or "").split(" ")[0].title()
            return prenom, (d.get("nom") or "").title(), d.get("qualite") or ""
    return "", "", ""


def distance_km(lat, lon, centre=VILLEFRANCHE):
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return None
    r = 6371
    p1, p2 = math.radians(centre[0]), math.radians(lat)
    dp, dl = p2 - p1, math.radians(lon - centre[1])
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return round(2 * r * math.asin(math.sqrt(a)), 1)


def dernier_ca(e):
    fin = e.get("finances") or {}
    if not fin:
        return None, None
    annee = max(fin)
    return (fin[annee] or {}).get("ca"), annee


def age_ans(date_creation):
    try:
        y, m, j = map(int, date_creation.split("-"))
        return round((date.today() - date(y, m, j)).days / 365.25, 1)
    except Exception:
        return None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dep", default="69,01", help="départements, ex. 69,01")
    p.add_argument("--rayon", type=float, default=40, help="rayon en km autour de Villefranche-sur-Saône")
    p.add_argument("--ca-min", type=float, default=150000, help="CA minimum si publié (sinon on garde la ligne)")
    p.add_argument("--naf", default="43.22A,43.22B", help="codes NAF séparés par des virgules")
    p.add_argument("--max", type=int, default=400)
    p.add_argument("--age-min", type=float, default=3.0, help="ancienneté minimum en années")
    a = p.parse_args()

    lignes, vus, page = [], set(), 1
    while len(lignes) < a.max:
        data = appel({
            "activite_principale": a.naf,
            "departement": a.dep,
            "etat_administratif": "A",
            "tranche_effectif_salarie": ",".join(TRANCHES_CIBLES),
            "per_page": 25,
            "page": page,
        })
        res = data.get("results") or []
        if not res:
            break
        for e in res:
            siren = e.get("siren")
            if siren in vus:
                continue
            vus.add(siren)
            s = e.get("siege") or {}
            age = age_ans(e.get("date_creation") or "")
            if age is None or age < a.age_min:
                continue
            if not str(e.get("nature_juridique") or "").startswith(FORMES_OK):
                continue
            km = distance_km(s.get("latitude"), s.get("longitude"))
            if km is None or km > a.rayon:
                continue
            ca, annee_ca = dernier_ca(e)
            if ca is not None and ca < a.ca_min:
                continue
            tranche = e.get("tranche_effectif_salarie") or s.get("tranche_effectif_salarie") or ""
            if tranche not in TRANCHES_CIBLES:
                continue
            enseignes = s.get("liste_enseignes") or []
            nom_commercial = (enseignes[0] if enseignes else (s.get("nom_commercial") or e.get("nom_raison_sociale") or e.get("nom_complet") or "")).title()
            prenom, nom, qualite = gerant(e)
            score = (SCORE_TRANCHE.get(tranche, 0) + (1 if age >= 5 else 0) + (1 if prenom else 0)
                     + (2 if ca and ca >= 300000 else 0) + (1 if km <= 15 else 0))
            lignes.append({
                "Entreprise": nom_commercial,
                "Raison sociale": e.get("nom_complet") or "",
                "Ville": (s.get("libelle_commune") or "").title(),
                "Distance (km)": km,
                "Forme juridique (code)": e.get("nature_juridique") or "",
                "CA publié (€)": ca if ca is not None else "",
                "Année CA": annee_ca or "",
                "Code postal": s.get("code_postal") or "",
                "Métier (NAF)": s.get("activite_principale") or e.get("activite_principale") or "",
                "Prénom gérant": prenom,
                "Nom gérant": nom,
                "Qualité": qualite,
                "SIREN": siren,
                "Effectif": TRANCHES_CIBLES[tranche],
                "Ancienneté (ans)": age,
                "Score SIRENE": score,
                "Recherche Google": "https://www.google.com/search?q=" + urllib.parse.quote_plus(f"{nom_commercial} {(s.get('libelle_commune') or '')} téléphone"),
                # À compléter à la main sur Google Maps / Pages Jaunes :
                "Mobile (06/07 publié)": "",
                "Source du numéro": "",
                "Note Google": "",
                "Nb avis": "",
                "Avis 'injoignable' ?": "",
                "Clients particuliers visibles ? (fiche Google, site, avis)": "",
                "Garder ? (O/N)": "",
            })
        if page >= (data.get("total_pages") or 1):
            break
        page += 1
        time.sleep(0.2)  # l'API limite à environ 7 requêtes par seconde

    lignes.sort(key=lambda l: -l["Score SIRENE"])
    sortie = "prospects_villefranche.csv"
    with open(sortie, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(lignes[0].keys()) if lignes else ["vide"], delimiter=";")
        w.writeheader()
        w.writerows(lignes[: a.max])
    print(f"{len(lignes[: a.max])} entreprises écrites dans {sortie}")


if __name__ == "__main__":
    main()
