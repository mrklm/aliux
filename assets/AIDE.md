
# Aliux 🐧

Aliux permet d’installer facilement des **AppImage** dans le menu des applications Linux,
sans passer par le terminal.

---

## Installation rapide

1. Cliquer sur **Choisir…** et sélectionner une AppImage
2. Vérifier / ajuster :
   - Nom
   - Description
   - Catégorie
   - Dossier d’installation
3. (Optionnel) Gérer l’icône :
   - Extraction automatique depuis l’AppImage
   - ou **Chemin icône…** pour fournir une icône manuellement
4. Cliquer sur **Installer**

L’application apparaît ensuite dans le menu du système.

---

## Icônes

- Par défaut, Aliux tente d’extraire l’icône depuis l’AppImage
- Si aucune icône correcte n’est trouvée, une icône générique est utilisée
- Le bouton **Chemin icône…** permet de forcer une icône personnalisée  
  (PNG, SVG, ICO…)

---

## Désinstallation

Bouton **Désinstaller…** :
- Supprime le lanceur `.desktop`
- Supprime l’AppImage (si elle a été installée par Aliux)
- Supprime l’icône associée

---

## Interface

- 🌙 : active / désactive le mode sombre
- ? : affiche cette aide dans le journal  
  (l’aide disparaît automatiquement dès qu’une action écrit dans le journal)

---

## Aliux dans le menu

Le bouton **Installer Aliux dans le menu** ajoute Aliux au menu des applications.  
(Tant qu’Aliux n’est pas packagé, ce lanceur utilise `python3 + aliux.py`.)

---

## Portée

- Installation **utilisateur uniquement** (pas de sudo)
- Compatible Ubuntu / environnements basés sur `.desktop`
- Formats supportés : **AppImage**

---

Aliux fait une chose, et la fait proprement.
