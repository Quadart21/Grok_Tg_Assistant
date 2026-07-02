from __future__ import annotations

import customtkinter as ctk


def section_title(parent, text: str, row: int, columnspan: int = 2) -> None:
    ctk.CTkLabel(
        parent,
        text=text,
        font=ctk.CTkFont(size=15, weight="bold"),
        anchor="w",
    ).grid(row=row, column=0, columnspan=columnspan, sticky="ew", padx=12, pady=(16, 4))


def hint_label(parent, text: str, row: int, columnspan: int = 2) -> None:
    ctk.CTkLabel(
        parent,
        text=text,
        anchor="w",
        text_color="#aaaaaa",
        wraplength=700,
        justify="left",
    ).grid(row=row, column=0, columnspan=columnspan, sticky="ew", padx=12, pady=(0, 8))


def labeled_entry(
    parent,
    row: int,
    label: str,
    placeholder: str = "",
    show: str | None = None,
    width_label: int = 180,
) -> ctk.CTkEntry:
    ctk.CTkLabel(parent, text=label, anchor="w", width=width_label).grid(
        row=row, column=0, sticky="w", padx=12, pady=6
    )
    entry = ctk.CTkEntry(parent, placeholder_text=placeholder, show=show)
    entry.grid(row=row, column=1, sticky="ew", padx=12, pady=6)
    return entry
