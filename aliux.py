#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import sys
import shutil
import stat
import subprocess
import tempfile
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# Pillow (optionnel, recommandé pour un resize propre)
try:
    from PIL import Image, ImageTk  # type: ignore
    PIL_OK = True
except Exception:
    PIL_OK = False


APP_TITLE = "Aliux"
APP_VERSION = "0.1.3"


DEFAULT_INSTALL_DIR = os.path.join(os.path.expanduser("~"), "Applications")

DESKTOP_DIR = os.path.join(os.path.expanduser("~"), ".local", "share", "applications")
ICON_DIR = os.path.join(os.path.expanduser("~"), ".local", "share", "icons", "aliux")

ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
HEADER_IMAGE_PATH = os.path.join(ASSETS_DIR, "aliux.png")
HELP_MD_PATH = os.path.join(ASSETS_DIR, "AIDE.md")

# Taille max bannière (réglage simple)
HEADER_MAX_W = 510
HEADER_MAX_H = 165

ALIUX_DESKTOP_TAG = "X-Aliux-Installer"
ALIUX_DESKTOP_TAG_VALUE = "true"


CATEGORY_MAP = {
    "Audio": "AudioVideo;Audio;",
    "Vidéo": "AudioVideo;Video;",
    "Graphisme": "Graphics;",
    "Bureautique": "Office;",
    "Développement": "Development;",
    "Utilitaire": "Utility;",
    "Réseau / Internet": "Network;",
    "Système": "System;",
    "Jeux": "Game;",
}


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def slugify(name: str) -> str:
    s = name.strip().lower()
    s = re.sub(r"[^\w\s-]", "", s, flags=re.UNICODE)
    s = re.sub(r"[\s_-]+", "-", s, flags=re.UNICODE).strip("-")
    return s or "appimage"


def set_executable(path: str) -> None:
    st = os.stat(path)
    # Rendre exécutable pour l'utilisateur, le groupe et les autres (équivalent chmod +x)
    os.chmod(path, st.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    
def default_browse_dir() -> str:
    """Dossier de départ pour les boîtes de dialogue (priorité aux supports amovibles)."""
    user = os.environ.get("USER") or os.environ.get("USERNAME") or ""
    candidates = []
    if user:
        candidates.append(os.path.join("/media", user))
        candidates.append(os.path.join("/run", "media", user))
    candidates.append("/media")
    candidates.append(os.path.expanduser("~"))

    for p in candidates:
        if p and os.path.isdir(p):
            return p
    return os.path.expanduser("~")
    

# ---------------------------------------------------------------------------
# Bootstrap (auto-install Aliux depuis un support non exécutable)
# ---------------------------------------------------------------------------

_BAD_EXEC_FSTYPES = {"vfat", "msdos", "fat", "exfat", "ntfs", "ntfs3", "cifs", "smbfs"}


def _parse_proc_mounts() -> list[tuple[str, str, str, set[str]]]:
    """Retourne une liste de mounts (mountpoint, fstype, device, options)."""
    mounts: list[tuple[str, str, str, set[str]]] = []
    try:
        with open("/proc/mounts", "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                parts = line.split()
                if len(parts) < 4:
                    continue
                device, mnt, fstype, opts = parts[0], parts[1], parts[2], parts[3]
                mounts.append((mnt, fstype, device, set(opts.split(","))))
    except Exception:
        return []
    return mounts


def find_mount_for_path(path: str) -> tuple[str, str, set[str]] | None:
    """Trouve le mount le plus spécifique contenant `path`.

    Retour: (mountpoint, fstype, options) ou None.
    """
    try:
        path = os.path.realpath(path)
    except Exception:
        return None

    best: tuple[str, str, set[str]] | None = None
    best_len = -1
    for mnt, fstype, _dev, opts in _parse_proc_mounts():
        # /proc/mounts utilise parfois des échappements (\040). os.path.realpath ne le fait pas.
        mnt_norm = mnt.replace("\\040", " ")
        if path == mnt_norm or path.startswith(mnt_norm.rstrip(os.sep) + os.sep):
            if len(mnt_norm) > best_len:
                best = (mnt_norm, fstype, opts)
                best_len = len(mnt_norm)
    return best


def is_non_executable_mount(path: str) -> bool:
    """Détermine si `path` est sur un support où exécuter une AppImage est problématique."""
    mi = find_mount_for_path(path)
    if not mi:
        return False
    _mnt, fstype, opts = mi
    if "noexec" in opts:
        return True
    if fstype.lower() in _BAD_EXEC_FSTYPES:
        return True
    return False


def ensure_self_local_copy() -> str | None:
    """Copie l'AppImage d'Aliux dans ~/Applications/Aliux/ et la rend exécutable.

    Retourne le chemin de l'AppImage locale, ou None si non applicable.
    """
    src = os.environ.get("APPIMAGE")
    if not src or not os.path.isfile(src):
        return None

    dest_dir = os.path.join(DEFAULT_INSTALL_DIR, "Aliux")
    dest = os.path.join(dest_dir, "Aliux.AppImage")

    try:
        ensure_dir(dest_dir)
        # Si déjà au bon endroit, ne rien faire
        if os.path.realpath(src) != os.path.realpath(dest):
            shutil.copy2(src, dest)
        set_executable(dest)
        return dest
    except Exception:
        return None


def bootstrap_offer_install(parent: tk.Misc | None = None) -> None:
    """Si Aliux est lancé depuis un support non exécutable (ex: clé vfat), proposer une installation locale.

    But: aucun terminal, aucun chmod manuel.
    """
    src = os.environ.get("APPIMAGE")
    if not src or not os.path.isfile(src):
        return

    # Si déjà lancé depuis l'emplacement local attendu, ne rien proposer
    expected = os.path.join(DEFAULT_INSTALL_DIR, "Aliux", "Aliux.AppImage")
    try:
        if os.path.realpath(src) == os.path.realpath(expected):
            return
    except Exception:
        pass

    if not is_non_executable_mount(src):
        # Support exécutable: rien à faire
        return

    user = os.environ.get("USER") or os.environ.get("USERNAME") or ""
    mount_hint = ""
    mi = find_mount_for_path(src)
    if mi:
        mnt, fstype, _opts = mi
        mount_hint = f"\n\nSupport détecté : {fstype} monté sur :\n{mnt}"

    msg = (
        "Aliux est lancé depuis un support où l'exécution des AppImage est souvent bloquée "
        "(par exemple une clé USB en FAT/vfat).\n\n"
        "Aliux peut se copier automatiquement dans votre dossier personnel "
        "et se relancer depuis cet emplacement (recommandé)."
        f"{mount_hint}\n\n"
        "Souhaitez-vous installer Aliux sur cet ordinateur maintenant ?"
    )

    try:
        ok = messagebox.askyesno("Installer Aliux", msg, parent=parent) if parent else messagebox.askyesno("Installer Aliux", msg)
    except Exception:
        return

    if not ok:
        return

    dest = ensure_self_local_copy()
    if not dest:
        try:
            messagebox.showerror(
                "Installer Aliux",
                "Impossible de copier Aliux dans ~/Applications/Aliux/.\n"
                "Veuillez copier manuellement l'AppImage sur votre disque puis relancer.",
                parent=parent,
            )
        except Exception:
            pass
        return

    # Relancer l'AppImage locale puis quitter l'instance actuelle (USB)
    try:
        subprocess.Popen([dest], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except Exception:
        # En dernier recours, essayer sans redirections
        try:
            subprocess.Popen([dest], start_new_session=True)
        except Exception:
            pass

    try:
        if parent is not None:
            parent.after(150, parent.destroy)
    except Exception:
        pass


def read_text_file(path: str, max_bytes: int = 300_000) -> str:
    with open(path, "rb") as f:
        data = f.read(max_bytes)
    try:
        return data.decode("utf-8", errors="replace")
    except Exception:
        return data.decode(errors="replace")


def parse_desktop_file(desktop_path: str) -> dict:
    """Parse simple d'un .desktop (section [Desktop Entry]) -> dict clé=valeur."""
    out = {}
    txt = read_text_file(desktop_path)
    in_entry = False
    for line in txt.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            in_entry = (line == "[Desktop Entry]")
            continue
        if not in_entry:
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _fit_header_image(path: str, max_w: int, max_h: int) -> tk.PhotoImage:
    """
    Charge une image depuis 'path' et la redimensionne pour tenir dans max_w/max_h.
    - Si Pillow est dispo : resize haute qualité (LANCZOS)
    - Sinon : fallback Tkinter (subsample) moins joli
    """
    if PIL_OK:
        img = Image.open(path).convert("RGBA")
        w, h = img.size
        if w <= 0 or h <= 0:
            return ImageTk.PhotoImage(img)

        scale = min(max_w / w, max_h / h, 1.0)  # ne pas agrandir
        new_w = max(1, int(w * scale))
        new_h = max(1, int(h * scale))
        if (new_w, new_h) != (w, h):
            img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        return ImageTk.PhotoImage(img)

    img0 = tk.PhotoImage(file=path)
    w = img0.width()
    h = img0.height()
    if w <= 0 or h <= 0:
        return img0
    factor = 1
    while (w // factor) > max_w or (h // factor) > max_h:
        factor += 1
        if factor > 20:
            break
    return img0 if factor == 1 else img0.subsample(factor, factor)


def find_best_icon_in_extract(root_dir: str, icon_hint: str | None) -> str | None:
    """Cherche une icône PNG/SVG dans l'AppImage extraite."""
    candidates: list[str] = []

    def walk_files():
        for base, _dirs, files in os.walk(root_dir):
            for fn in files:
                low = fn.lower()
                if low.endswith(".png") or low.endswith(".svg"):
                    yield os.path.join(base, fn)

    # 1) hint (Icon=)
    if icon_hint:
        hint = icon_hint.strip()
        possible = {hint, os.path.basename(hint), os.path.splitext(os.path.basename(hint))[0]}
        for p in walk_files():
            bn = os.path.basename(p)
            bn_noext = os.path.splitext(bn)[0]
            if bn in possible or bn_noext in possible:
                candidates.append(p)
        pngs = [c for c in candidates if c.lower().endswith(".png")]
        svgs = [c for c in candidates if c.lower().endswith(".svg")]
        if pngs:
            return max(pngs, key=lambda x: os.path.getsize(x))
        if svgs:
            return svgs[0]

    # 2) hicolor apps
    hicolor = os.path.join(root_dir, "usr", "share", "icons", "hicolor")
    if os.path.isdir(hicolor):
        for base, _dirs, files in os.walk(hicolor):
            if os.path.basename(base) != "apps":
                continue
            for fn in files:
                low = fn.lower()
                if low.endswith(".png") or low.endswith(".svg"):
                    candidates.append(os.path.join(base, fn))
        if candidates:
            pngs = [c for c in candidates if c.lower().endswith(".png")]
            if pngs:
                return max(pngs, key=lambda x: os.path.getsize(x))
            return candidates[0]

    # 3) biggest PNG anywhere
    all_png = [p for p in walk_files() if p.lower().endswith(".png")]
    if all_png:
        return max(all_png, key=lambda x: os.path.getsize(x))

    # 4) any SVG
    all_svg = [p for p in walk_files() if p.lower().endswith(".svg")]
    if all_svg:
        return all_svg[0]

    return None


def try_extract_appimage_metadata(appimage_path: str) -> tuple[str | None, str | None, str | None]:
    """Retourne (suggested_name, icon_file_path, icon_hint) via --appimage-extract."""
    try:
        set_executable(appimage_path)
    except Exception:
        pass

    with tempfile.TemporaryDirectory(prefix="aliux-extract-") as td:
        try:
            proc = subprocess.run(
                [appimage_path, "--appimage-extract"],
                cwd=td,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=120,
            )
        except Exception:
            return (None, None, None)

        if proc.returncode != 0:
            return (None, None, None)

        root_dir = os.path.join(td, "squashfs-root")
        if not os.path.isdir(root_dir):
            return (None, None, None)

        desktop_found = None
        for fn in os.listdir(root_dir):
            if fn.lower().endswith(".desktop"):
                desktop_found = os.path.join(root_dir, fn)
                break
        if not desktop_found:
            maybe = os.path.join(root_dir, "usr", "share", "applications")
            if os.path.isdir(maybe):
                for fn in os.listdir(maybe):
                    if fn.lower().endswith(".desktop"):
                        desktop_found = os.path.join(maybe, fn)
                        break

        suggested_name = None
        icon_hint = None
        if desktop_found and os.path.isfile(desktop_found):
            data = parse_desktop_file(desktop_found)
            suggested_name = data.get("Name") or data.get("Name[fr]") or data.get("Name[en]")
            icon_hint = data.get("Icon")

        icon_file_path = find_best_icon_in_extract(root_dir, icon_hint)
        return (suggested_name, icon_file_path, icon_hint)


def list_aliux_installs() -> list[dict]:
    """
    Liste les applis installées par Aliux (tag X-Aliux-Installer=true).
    Retourne une liste de dict: {name, desktop_path, appimage_path, icon_path}
    """
    out: list[dict] = []
    if not os.path.isdir(DESKTOP_DIR):
        return out

    for fn in os.listdir(DESKTOP_DIR):
        if not fn.endswith(".desktop"):
            continue
        dp = os.path.join(DESKTOP_DIR, fn)
        try:
            data = parse_desktop_file(dp)
        except Exception:
            continue

        if data.get(ALIUX_DESKTOP_TAG) != ALIUX_DESKTOP_TAG_VALUE:
            continue

        name = data.get("Name", fn)
        appimage_path = data.get("X-Aliux-AppImagePath")
        icon_path = data.get("X-Aliux-IconPath")

        if not appimage_path:
            ex = data.get("Exec", "")
            m = re.search(r'"([^"]+\.AppImage)"', ex)
            if m:
                appimage_path = m.group(1)

        if not icon_path:
            icon = data.get("Icon", "")
            if icon.startswith("/") and os.path.exists(icon):
                icon_path = icon

        out.append(
            {
                "name": name,
                "desktop_path": dp,
                "appimage_path": appimage_path,
                "icon_path": icon_path,
            }
        )

    out.sort(key=lambda x: x.get("name", "").lower())
    return out


class AliuxApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_TITLE} v{APP_VERSION}")
        self.minsize(900, 650)

        self.var_file = tk.StringVar()
        self.var_name = tk.StringVar()
        self.var_desc = tk.StringVar()
        self.var_install_dir = tk.StringVar(value=DEFAULT_INSTALL_DIR)
        self.var_category = tk.StringVar(value=list(CATEGORY_MAP.keys())[0])
        self.var_extract_icon = tk.BooleanVar(value=True)

        # Icône manuelle (option)
        self.var_icon_path = tk.StringVar(value="")

        # 🌙 mode sombre (coché par défaut)
        self.var_dark = tk.BooleanVar(value=True)

        # ? Aide (cochée au démarrage)
        self.var_help = tk.BooleanVar(value=True)

        # Dossier de départ pour les sélecteurs de fichiers (USB / media)
        self.last_browse_dir = default_browse_dir()

        # Références images (sinon Tkinter les perd)
        self._header_img = None

        self._build_ui()

        # applique thème initial
        self._apply_theme(self.var_dark.get())

        # tente icône de fenêtre
        self._apply_window_icon()

        # affiche l'aide au démarrage
        self._show_help(force=True)

        # Bootstrap: si Aliux est lancé depuis un support non exécutable (clé FAT/vfat),
        # proposer une installation locale puis relancer automatiquement.
        self.after(350, lambda: bootstrap_offer_install(self))

    def _apply_window_icon(self):
        try:
            if os.path.isfile(HEADER_IMAGE_PATH):
                self.iconphoto(True, tk.PhotoImage(file=HEADER_IMAGE_PATH))
        except Exception:
            pass

    def _apply_theme(self, dark: bool):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        if dark:
            bg = "#121212"
            fg = "#E8E8E8"
            card = "#1B1B1B"
            field = "#202020"
            border = "#2A2A2A"
        else:
            bg = "#F2F2F2"
            fg = "#121212"
            card = "#FFFFFF"
            field = "#FFFFFF"
            border = "#D0D0D0"

        self.configure(background=bg)

        style.configure(".", background=bg, foreground=fg)
        style.configure("TFrame", background=bg)
        style.configure("TLabel", background=bg, foreground=fg)
        style.configure("TLabelframe", background=bg, foreground=fg, bordercolor=border)
        style.configure("TLabelframe.Label", background=bg, foreground=fg)

        style.configure("TButton", background=card, foreground=fg)
        style.map("TButton", background=[("active", card)])

        style.configure("TEntry", fieldbackground=field, foreground=fg)
        style.configure("TCombobox", fieldbackground=field, foreground=fg)

        style.configure("TCheckbutton", background=bg, foreground=fg)
        style.map("TCheckbutton", background=[("active", bg)])

        try:
            self.txt_log.configure(
                background=field,
                foreground=fg,
                insertbackground=fg,
                highlightbackground=border,
                highlightcolor=border,
            )
        except Exception:
            pass

    def _clear_log(self):
        self.txt_log.configure(state="normal")
        self.txt_log.delete("1.0", "end")
        self.txt_log.configure(state="disabled")

    def _show_help(self, force: bool = False):
        """
        Affiche assets/AIDE.md dans le journal si la case ? est cochée.
        - force=True : affiche même si var_help est décochée (utile au démarrage)
        """
        if not force and not self.var_help.get():
            return

        self._clear_log()
        if os.path.isfile(HELP_MD_PATH):
            content = read_text_file(HELP_MD_PATH, max_bytes=600_000)
        else:
            content = (
                "AIDE.md introuvable.\n\n"
                "Veuillez créer : assets/AIDE.md\n"
            )

        self.txt_log.configure(state="normal")
        self.txt_log.delete("1.0", "end")
        self.txt_log.insert("1.0", content.rstrip() + "\n")

        # FORCER l'affichage en haut
        self.txt_log.mark_set("insert", "1.0")
        self.txt_log.yview_moveto(0.0)

        self.txt_log.configure(state="disabled")


        # s'assurer qu'elle est cochée
        self.var_help.set(True)

    def log(self, msg: str):
        # Si l'aide est affichée et qu'on doit logger autre chose :
        # - décocher ?
        # - effacer le journal
        if self.var_help.get():
            self.var_help.set(False)
            self._clear_log()

        self.txt_log.configure(state="normal")
        self.txt_log.insert("end", msg.rstrip() + "\n")
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

    def set_status(self, msg: str):
        self.lbl_status.configure(text=msg)
        self.update_idletasks()

    def _build_ui(self):
        pad = 10
        main = ttk.Frame(self, padding=pad)
        main.pack(fill="both", expand=True)

        # ---- Top bar ( ? à gauche / 🌙 à droite )
        topbar = ttk.Frame(main)
        topbar.pack(fill="x")

        left_controls = ttk.Frame(topbar)
        left_controls.pack(side="left", anchor="nw")

        right_controls = ttk.Frame(topbar)
        right_controls.pack(side="right", anchor="ne")

        chk_help = ttk.Checkbutton(
            left_controls,
            text="?",
            variable=self.var_help,
            command=lambda: self._show_help(force=False) if self.var_help.get() else None,
        )
        chk_help.pack(side="left", anchor="nw")

        chk_dark = ttk.Checkbutton(
            right_controls,
            text="🌙",
            variable=self.var_dark,
            command=lambda: self._apply_theme(self.var_dark.get()),
        )
        chk_dark.pack(side="right", anchor="ne")

        # ---- Header image (bannière)
        header_frame = ttk.Frame(main)
        header_frame.pack(fill="x")

        if os.path.isfile(HEADER_IMAGE_PATH):
            try:
                self._header_img = _fit_header_image(HEADER_IMAGE_PATH, HEADER_MAX_W, HEADER_MAX_H)
                lbl = ttk.Label(header_frame, image=self._header_img)
                lbl.pack(anchor="center", pady=(6, 8))
            except Exception as e:
                ttk.Label(header_frame, text=f"(Image non affichée : {e})").pack(anchor="center", pady=(6, 8))
        else:
            ttk.Label(header_frame, text="(Image introuvable : assets/aliux.png)").pack(anchor="center", pady=(6, 8))

        # ---- File row
        frm_file = ttk.LabelFrame(main, text="Fichier AppImage")
        frm_file.pack(fill="x")

        row = ttk.Frame(frm_file)
        row.pack(fill="x", padx=pad, pady=(pad, 0))

        ttk.Button(row, text="Choisir…", command=self.on_choose_file).pack(side="left")
        ttk.Button(row, text="🔄", width=3, command=self.on_refresh_mounts).pack(side="left", padx=(6, 0))
        ttk.Entry(row, textvariable=self.var_file).pack(side="left", fill="x", expand=True, padx=(10, 0))


        hint = ttk.Label(frm_file, text="Veuillez sélectionner un fichier .AppImage.")
        hint.pack(anchor="w", padx=pad, pady=(6, pad))

        # ---- Settings
        frm_set = ttk.LabelFrame(main, text="Paramètres")
        frm_set.pack(fill="x", pady=(pad, 0))

        grid = ttk.Frame(frm_set)
        grid.pack(fill="x", expand=True, anchor="w", padx=pad, pady=pad)

        
        grid.grid_anchor("w")
        grid.columnconfigure(0, weight=0)
        grid.columnconfigure(1, weight=1)


        ttk.Label(grid, text="Nom :").grid(row=0, column=0, sticky="w", pady=4, padx=(0, 10))
        ttk.Entry(grid, textvariable=self.var_name).grid(row=0, column=1, sticky="ew", pady=4)

        ttk.Label(grid, text="Description :").grid(row=1, column=0, sticky="w", pady=4, padx=(0, 10))
        ttk.Entry(grid, textvariable=self.var_desc).grid(row=1, column=1, sticky="ew", pady=4)


        ttk.Label(grid, text="Catégorie :").grid(row=2, column=0, sticky="w", pady=4, padx=(0, 10))
        ttk.Combobox(
            grid,
            textvariable=self.var_category,
            values=list(CATEGORY_MAP.keys()),
            state="readonly",
            width=25,
        ).grid(row=2, column=1, sticky="ew", pady=4)


        # Ligne extraction icône + bouton chemin icône (dans une ligne dédiée)
        row_icon = ttk.Frame(grid)
        row_icon.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(8, 0))

        ttk.Checkbutton(
            row_icon,
            variable=self.var_extract_icon,
            text="Tenter d’extraire une icône depuis l’AppImage (recommandé)",
        ).pack(side="left", anchor="w")

        ttk.Button(
            row_icon,
            text="Chemin icône…",
            command=self.on_choose_icon_path,
        ).pack(side="right")

        # Affichage du chemin icône (optionnel mais pratique)
        ttk.Label(grid, text="Icône :").grid(row=5, column=0, sticky="w", pady=(6, 0), padx=(0, 10))

        ent_icon = ttk.Entry(grid, textvariable=self.var_icon_path, state="readonly")
        ent_icon.grid(row=5, column=1, sticky="ew", pady=(6, 0))



        # ---- Actions
        frm_act = ttk.Frame(main)
        frm_act.pack(fill="x", pady=(pad, 0))

        self.btn_install = ttk.Button(frm_act, text="Installer", command=self.on_install_clicked)
        self.btn_install.pack(side="left")

        ttk.Button(frm_act, text="Désinstaller…", command=self.on_uninstall_dialog).pack(side="left", padx=(10, 0))

        # Spacer qui pousse le bouton Aliux tout à droite
        spacer = ttk.Frame(frm_act)
        spacer.pack(side="left", fill="x", expand=True)

        ttk.Button(frm_act, text="Installer Aliux dans le menu", command=self.on_install_aliux_desktop).pack(
            side="right"
        )

        self.lbl_status = ttk.Label(frm_act, text="")
        self.lbl_status.pack(side="left", padx=(12, 0))

        # ---- Log
        frm_log = ttk.LabelFrame(main, text="Journal")
        frm_log.pack(fill="both", expand=True, pady=(pad, 0))

        self.txt_log = tk.Text(frm_log, height=12, wrap="word")
        self.txt_log.pack(fill="both", expand=True, padx=pad, pady=pad)
        self.txt_log.configure(state="disabled")
        
    def on_refresh_mounts(self):
        self.last_browse_dir = default_browse_dir()
        self.log(f"🔄 Dossier de navigation mis à jour : {self.last_browse_dir}")


    def on_choose_file(self):
        path = filedialog.askopenfilename(
            title="Veuillez choisir un fichier AppImage",
            initialdir=self.last_browse_dir,
            filetypes=[("AppImage", "*.AppImage *.appimage"), ("Tous les fichiers", "*.*")]
        )

        if not path:
            return

        self.last_browse_dir = os.path.dirname(path)
        self.var_file.set(path)
        self.log(f"Fichier sélectionné : {path}")

        base = os.path.basename(path)
        base_noext = re.sub(r"\.(?i:appimage)$", "", base).strip()

        if not self.var_name.get().strip():
            self.var_name.set(base_noext)

        if self.var_extract_icon.get():
            def _worker():
                self.set_status("Analyse AppImage…")
                suggested_name, _icon, _hint = try_extract_appimage_metadata(path)
                if suggested_name:
                    current = self.var_name.get().strip()
                    if not current or current == base_noext:
                        self.var_name.set(suggested_name)
                self.set_status("")

            threading.Thread(target=_worker, daemon=True).start()

    def on_choose_dir(self):
        path = filedialog.askdirectory(
            title="Veuillez choisir un dossier d’installation",
            initialdir=self.var_install_dir.get() or os.path.expanduser("~"),
        )
        if not path:
            return
        self.var_install_dir.set(path)
        self.log(f"Dossier d’installation : {path}")

    def on_choose_icon_path(self):
        path = filedialog.askopenfilename(
            title="Veuillez choisir une icône",
            initialdir=self.last_browse_dir,
            filetypes=[("Images", "*.png *.svg *.ico"), ("Tous les fichiers", "*.*")]
        )

        if not path:
            return
        
        self.last_browse_dir = os.path.dirname(path)
        self.var_icon_path.set(path)
        self.log(f"Icône sélectionnée : {path}")

    def _validate(self) -> tuple[bool, str]:
        f = self.var_file.get().strip()
        if not f or not os.path.isfile(f):
            return (False, "Veuillez sélectionner un fichier AppImage valide.")
        name = self.var_name.get().strip()
        if not name:
            return (False, "Veuillez renseigner un nom d’application.")
        install_dir = self.var_install_dir.get().strip()
        if not install_dir:
            return (False, "Veuillez choisir un dossier d’installation.")
        return (True, "")

    def on_install_clicked(self):
        ok, err = self._validate()
        if not ok:
            messagebox.showerror("Erreur", err)
            return
        self.btn_install.configure(state="disabled")
        threading.Thread(target=self._install_worker, daemon=True).start()

    def _install_worker(self):
        try:
            self.set_status("Installation en cours…")

            src = self.var_file.get().strip()
            name = self.var_name.get().strip()
            desc = self.var_desc.get().strip()
            cat_human = self.var_category.get().strip()
            categories = CATEGORY_MAP.get(cat_human, "Utility;")
            install_dir = self.var_install_dir.get().strip()

            manual_icon = self.var_icon_path.get().strip()
            if manual_icon and not os.path.isfile(manual_icon):
                manual_icon = ""

            ensure_dir(install_dir)
            ensure_dir(DESKTOP_DIR)
            ensure_dir(ICON_DIR)

            slug = slugify(name)

            dst_appimage = os.path.join(install_dir, f"{slug}.AppImage")

            if os.path.exists(dst_appimage):
                choice = {"val": None}

                def _ask():
                    choice["val"] = messagebox.askyesno(
                        "Remplacement",
                        "Un fichier AppImage avec ce nom existe déjà.\n\nSouhaitez-vous le remplacer ?",
                    )

                self.after(0, _ask)
                while choice["val"] is None:
                    self.after(50)
                    self.update()

                if not choice["val"]:
                    self.log("Installation annulée (fichier existant).")
                    return

            self.log(f"Copie vers : {dst_appimage}")
            shutil.copy2(src, dst_appimage)
            set_executable(dst_appimage)
            self.log("Permissions : exécutable (chmod +x)")

            # Icône : priorité à l'icône manuelle
            icon_dst = None

            if manual_icon:
                self.log("Icône : utilisation du chemin d’icône sélectionné.")
                ext = os.path.splitext(manual_icon)[1].lower()
                if ext not in (".png", ".svg", ".ico", ".jpg", ".jpeg"):
                    ext = ".png"
                icon_dst = os.path.join(ICON_DIR, f"{slug}{ext}")
                shutil.copy2(manual_icon, icon_dst)
                self.log(f"Icône copiée : {icon_dst}")
            elif self.var_extract_icon.get():
                self.log("Extraction d’icône : tentative via --appimage-extract…")
                _suggested_name, icon_src, _icon_hint = try_extract_appimage_metadata(dst_appimage)
                if icon_src and os.path.isfile(icon_src):
                    ext = os.path.splitext(icon_src)[1].lower()
                    if ext not in (".png", ".svg"):
                        ext = ".png"
                    icon_dst = os.path.join(ICON_DIR, f"{slug}{ext}")
                    shutil.copy2(icon_src, icon_dst)
                    self.log(f"Icône extraite : {icon_dst}")
                else:
                    self.log("Icône : aucune icône exploitable trouvée dans l’AppImage.")
            else:
                self.log("Icône : extraction désactivée.")

            desktop_path = os.path.join(DESKTOP_DIR, f"{slug}.desktop")
            exec_line = f'"{dst_appimage}" %U'
            icon_line = icon_dst if icon_dst else "application-x-executable"

            desktop_content = (
                "[Desktop Entry]\n"
                "Type=Application\n"
                f"Name={name}\n"
                f"Comment={desc}\n"
                f"Exec={exec_line}\n"
                f"Icon={icon_line}\n"
                "Terminal=false\n"
                f"Categories={categories}\n"
                "StartupNotify=true\n"
                f"{ALIUX_DESKTOP_TAG}={ALIUX_DESKTOP_TAG_VALUE}\n"
                f"X-Aliux-AppImagePath={dst_appimage}\n"
                f"X-Aliux-IconPath={icon_dst or ''}\n"
            )

            self.log(f"Création du lanceur : {desktop_path}")
            with open(desktop_path, "w", encoding="utf-8") as f:
                f.write(desktop_content)

            self.log("Mise à jour du cache des lanceurs (optionnel)…")
            try:
                subprocess.run(
                    ["update-desktop-database", DESKTOP_DIR],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            except Exception:
                pass

            self.log("✅ Installation terminée.")
            self.after(
                0,
                lambda: messagebox.showinfo(
                    "Terminé",
                    "Installation terminée.\n\nL’application devrait apparaître dans le menu des applications.",
                ),
            )
        except Exception as e:
            self.log(f"❌ Erreur : {e}")
            self.after(0, lambda: messagebox.showerror("Erreur", f"Une erreur est survenue :\n\n{e}"))
        finally:
            self.set_status("")
            self.after(0, lambda: self.btn_install.configure(state="normal"))

    # ---------------------------
    # Désinstallation (dialog)
    # ---------------------------
    def on_uninstall_dialog(self):
        installs = list_aliux_installs()
        if not installs:
            messagebox.showinfo("Désinstallation", "Aucune application installée par Aliux n’a été trouvée.")
            return

        win = tk.Toplevel(self)
        win.title("Désinstaller une application")
        win.transient(self)
        win.grab_set()
        win.resizable(False, False)

        frm = ttk.Frame(win, padding=12)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="Veuillez choisir l’application à désinstaller :").pack(anchor="w")

        names = [i["name"] for i in installs]
        var_choice = tk.StringVar(value=names[0])

        cmb = ttk.Combobox(frm, values=names, textvariable=var_choice, state="readonly", width=55)
        cmb.pack(fill="x", pady=(8, 10))

        info = ttk.Label(frm, text="")
        info.pack(anchor="w", pady=(0, 10))

        def _refresh_info(*_):
            sel = var_choice.get()
            item = next((x for x in installs if x["name"] == sel), None)
            if not item:
                info.configure(text="")
                return
            dp = item.get("desktop_path") or ""
            ap = item.get("appimage_path") or ""
            info.configure(text=f".desktop : {dp}\nAppImage : {ap}")

        _refresh_info()
        cmb.bind("<<ComboboxSelected>>", _refresh_info)

        btn_row = ttk.Frame(frm)
        btn_row.pack(fill="x")

        def _do_uninstall():
            sel = var_choice.get()
            item = next((x for x in installs if x["name"] == sel), None)
            if not item:
                return
            if not messagebox.askyesno(
                "Confirmation",
                "Souhaitez-vous vraiment désinstaller cette application ?\n\n"
                "Cela supprimera le lanceur (.desktop) et, si possible, l’AppImage et l’icône.",
                parent=win,
            ):
                return

            removed = []
            errors = []

            dp = item.get("desktop_path")
            if dp and os.path.exists(dp):
                try:
                    os.remove(dp)
                    removed.append(dp)
                except Exception as e:
                    errors.append(f"{dp} : {e}")

            ap = item.get("appimage_path")
            if ap and os.path.exists(ap):
                try:
                    os.remove(ap)
                    removed.append(ap)
                except Exception as e:
                    errors.append(f"{ap} : {e}")

            ic = item.get("icon_path")
            if ic and os.path.exists(ic):
                try:
                    os.remove(ic)
                    removed.append(ic)
                except Exception as e:
                    errors.append(f"{ic} : {e}")

            try:
                subprocess.run(
                    ["update-desktop-database", DESKTOP_DIR],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            except Exception:
                pass

            for r in removed:
                self.log(f"🗑️ Supprimé : {r}")
            for e in errors:
                self.log(f"⚠️ Suppression : {e}")

            win.destroy()
            if errors:
                messagebox.showwarning("Désinstallation", "Désinstallation terminée avec avertissements.\n\nVoir le journal.")
            else:
                messagebox.showinfo("Désinstallation", "Désinstallation terminée.")

        ttk.Button(btn_row, text="Annuler", command=win.destroy).pack(side="right")
        ttk.Button(btn_row, text="Désinstaller", command=_do_uninstall).pack(side="right", padx=(0, 10))

    # ---------------------------
    # .desktop pour Aliux lui-même
    # ---------------------------

    def on_install_aliux_desktop(self):
        """Ajoute Aliux au menu des applications.

        - Si Aliux tourne en AppImage, copie d'abord l'AppImage en local (~/Applications/Aliux/)
          et crée un lanceur qui pointe vers cette AppImage (exécutable garanti).
        - Sinon, fallback: lance python3 + aliux.py (utile en dev).
        """
        try:
            ensure_dir(DESKTOP_DIR)
            ensure_dir(ICON_DIR)

            # Icône du lanceur (fallback: icône générique)
            icon_dst = None
            if os.path.isfile(HEADER_IMAGE_PATH):
                icon_dst = os.path.join(ICON_DIR, "aliux.png")
                try:
                    shutil.copy2(HEADER_IMAGE_PATH, icon_dst)
                except Exception:
                    icon_dst = None

            desktop_path = os.path.join(DESKTOP_DIR, "aliux.desktop")

            appimage_src = os.environ.get("APPIMAGE")
            if appimage_src and os.path.isfile(appimage_src):
                # Copier l'AppImage en local et garantir +x
                local_appimage = ensure_self_local_copy()
                target = local_appimage if (local_appimage and os.path.isfile(local_appimage)) else appimage_src
                exec_value = f'"{target}" %U'
            else:
                # Mode script (dev)
                script_path = os.path.abspath(__file__)
                exec_value = f'python3 "{script_path}"'

            desktop_content = (
                "[Desktop Entry]\n"
                "Type=Application\n"
                "Name=Aliux\n"
                "Comment=Installateur AppImage local\n"
                f"Exec={exec_value}\n"
                f"Icon={icon_dst if icon_dst else 'application-x-executable'}\n"
                "Terminal=false\n"
                "Categories=Utility;\n"
                "StartupNotify=true\n"
                "X-Aliux-Self=true\n"
            )

            with open(desktop_path, "w", encoding="utf-8") as f:
                f.write(desktop_content)

            try:
                subprocess.run(
                    ["update-desktop-database", DESKTOP_DIR],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            except Exception:
                pass

            self.log(f"✅ Lanceur Aliux créé : {desktop_path}")

            messagebox.showinfo(
                "Aliux",
                "Aliux a été ajouté au menu des applications.\n\n"
                "Si Aliux a été copié dans ~/Applications/Aliux/, le lanceur pointe vers cette copie locale.",
            )

        except Exception as e:
            self.log(f"❌ Erreur installation lanceur Aliux : {e}")
            messagebox.showerror("Aliux", f"Impossible de créer le lanceur Aliux.\n\n{e}")

if __name__ == "__main__":
    if os.name != "posix":
        tk.Tk().withdraw()
        messagebox.showerror(
            "Système non supporté",
            "Cet outil est prévu pour Linux (Ubuntu).\n\nLes lanceurs .desktop ne sont pas pris en charge sur ce système.",
        )
        raise SystemExit(1)

    app = AliuxApp()
    app.mainloop()
