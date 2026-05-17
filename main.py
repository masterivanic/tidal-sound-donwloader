"""
Tidal Desktop Downloader — main entry point
"""
import customtkinter as ctk
from app import TidalApp

if __name__ == "__main__":
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    app = TidalApp()
    app.mainloop()
