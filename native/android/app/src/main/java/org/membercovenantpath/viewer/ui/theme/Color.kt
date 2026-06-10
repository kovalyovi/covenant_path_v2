package org.membercovenantpath.viewer.ui.theme

import androidx.compose.ui.graphics.Color

/**
 * All the palette tokens, mirroring the Flutter app's color choices exactly so the two PoCs read
 * identically. Material 3 seed is Indigo (matching app_theme.dart `_seed = Colors.indigo`); the
 * rest are the deliberate, non-status accent palettes the Flutter code documents.
 */

// Seed (Colors.indigo == 0xFF3F51B5)
val Indigo = Color(0xFF3F51B5)

// ---- per-tab nav accents (dashboard_page.dart `_tabs`) -----------------------
object TabColors {
    val Baptisms = Color(0xFF0277BD)   // blue
    val GoldenHour = Color(0xFFF9A825) // gold/amber
    val Needs = Color(0xFFD84315)      // deep orange
    val Kpis = Color(0xFF2E7D32)       // green
    val Table = Color(0xFF5E35B1)      // deep purple
    // "By Month" is no longer its own tab — the chart now lives at the bottom of KPIs (#1).
}

// ---- org-ownership identity colors (golden_hour.dart `orgInfo`) --------------
object OrgColors {
    val WML = Color(0xFF00897B)        // teal
    val EQ = Color(0xFF1565C0)         // blue
    val RS = Color(0xFFAD1457)         // rose
    val Unassigned = Color(0xFF9E9E9E) // grey
}

// ---- milestone category colors (golden_hour.dart `milestones`) ---------------
object MilestoneColors {
    val Friends = Color(0xFFD81B60)               // pink
    val Calling = Color(0xFF6A1B9A)               // purple
    val HasMinisters = Color(0xFF00838F)          // cyan
    val MinisteringAssignment = Color(0xFFEF6C00) // orange
    val AaronicPriesthood = Color(0xFF1565C0)     // blue
    val MelchizedekPriesthood = Color(0xFF2E7D32) // green
    val FamilyName = Color(0xFF6D4C41)            // brown
    val FirstTempleVisit = Color(0xFF00897B)      // teal
}

// ---- status palette (chips, table cells) ------------------------------------
object StatusColors {
    val DoneGreen = Color(0xFF43A047)   // green.shade600
    val NextAmber = Color(0xFFFFB300)   // amber.shade700
    val NoRed = Color(0xFFE53935)       // red-ish
    val GreyBorder = Color(0xFFBDBDBD)  // grey.shade400
    val GreyText = Color(0xFF757575)    // grey.shade600

    // Table cell fills (Yes/No/N-A + recommend Active/Expired/No)
    val CellGreen = Color(0xFFC8E6C9)   // green.shade100
    val CellRed = Color(0xFFFFCDD2)     // red.shade100
    val CellGrey = Color(0xFFEEEEEE)    // grey.shade200
    val CellAmber = Color(0xFFFFECB3)   // amber.shade100
    val CellMaleBlue = Color(0xFFBBDEFB)
    val CellFemalePink = Color(0xFFF8BBD0)
}

// ---- per-unit accent palette (needs_view.dart `_unitPalette`) ----------------
// 16 visually distinct, text-legible hues so each ward in a stake reads as its own color. Assigned by
// sorted index via [unitColorMap] (not by hash) — hashCode % N produced near-duplicate colors when
// two ward names happened to collide on the modulus.
val UnitPalette = listOf(
    Color(0xFF00695C), Color(0xFF4527A0), Color(0xFFAD1457), Color(0xFF283593),
    Color(0xFF558B2F), Color(0xFF6D4C41), Color(0xFF00838F), Color(0xFFC62828),
    Color(0xFFEF6C00), Color(0xFF1565C0), Color(0xFF8E24AA), Color(0xFF2E7D32),
    Color(0xFF827717), Color(0xFF006064), Color(0xFFBF360C), Color(0xFF37474F),
)

/**
 * Assign each distinct unit its own palette color by **sorted index**, so every ward gets a different
 * hue (stable across the session and across category/org-filter changes). Only wraps the palette if a
 * stake somehow has more units than colors (16) — rare. Mirrors Flutter `_assignUnitColors`.
 */
fun unitColorMap(units: Collection<String>): Map<String, Color> =
    units.toSortedSet().withIndex().associate { (i, u) -> u to UnitPalette[i % UnitPalette.size] }

/** Stable per-unit color when the full unit set isn't handy (single-unit fallback). */
fun unitColor(unit: String): Color =
    UnitPalette[(unit.hashCode().let { if (it == Int.MIN_VALUE) 0 else kotlin.math.abs(it) }) % UnitPalette.size]
