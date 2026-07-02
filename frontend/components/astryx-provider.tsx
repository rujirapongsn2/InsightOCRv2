"use client"

import { Theme } from "@astryxdesign/core/theme"
import { neutralTheme } from "@astryxdesign/theme-neutral/built"

export function AstryxProvider({ children }: { children: React.ReactNode }) {
    return (
        <Theme theme={neutralTheme} mode="light">
            {children}
        </Theme>
    )
}
