"use client"
// Copyright © 2024 Ory Corp
// SPDX-License-Identifier: Apache-2.0

/**
 * This package provides the default theme for Ory Elements React.
 *
 * @packageDocumentation
 * @module default-theme
 */

// global.css is Tailwind 4 source. The webapp ships its compiled build
// (src/styles/ory-elements.css, imported by globals.css); importing the source
// here only added an unscoped copy of Tailwind 4 to every page using the theme
// and failed to parse under the webapp's Tailwind 3.
export * from "./components"
export * from "./flows"
