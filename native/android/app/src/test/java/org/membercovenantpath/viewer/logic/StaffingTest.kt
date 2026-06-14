package org.membercovenantpath.viewer.logic

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** Verifies the leadership/staffing gap rule (#12) mirrors web logic/staffing.ts exactly. */
class StaffingTest {

    private fun roster(vararg positions: String) =
        positions.mapIndexed { i, p -> StaffingMember(position = p, person = "Person $i") }

    @Test fun fullyStaffedWardHasNoGaps() {
        val r = roster(
            "Ward Mission Leader",
            "Ward Missionary", "Ward Missionary",
            "Elders Quorum President",
            "Relief Society President",
        )
        assertEquals(0, Staffing.gapCount(r))
        assertTrue(Staffing.gaps(r).all { it.ok })
    }

    @Test fun missingWmlAndTooFewMissionariesAreGaps() {
        // No WML; only 1 ward missionary (need 2); EQ + RS present.
        val r = roster(
            "Ward Missionary",
            "Elders Quorum President",
            "Relief Society President",
        )
        val byKey = Staffing.gaps(r).associateBy { it.key }
        assertFalse(byKey["wml"]!!.ok)              // no ward mission leader
        assertFalse(byKey["ward_missionaries"]!!.ok) // 1 < 2
        assertEquals(1, byKey["ward_missionaries"]!!.have)
        assertTrue(byKey["eq_pres"]!!.ok)
        assertTrue(byKey["rs_pres"]!!.ok)
        assertEquals(2, Staffing.gapCount(r))
    }

    @Test fun assistantWmlDoesNotFillTheLeaderSlot() {
        // An "Assistant Ward Mission Leader" must NOT satisfy the WML requirement.
        val r = roster("Assistant Ward Mission Leader")
        assertFalse(Staffing.gaps(r).first { it.key == "wml" }.ok)
    }

    @Test fun counselorsDoNotFillPresidentSlots() {
        val r = roster(
            "Elders Quorum First Counselor",
            "Relief Society Secretary",
        )
        val byKey = Staffing.gaps(r).associateBy { it.key }
        assertFalse(byKey["eq_pres"]!!.ok) // counselor ≠ president
        assertFalse(byKey["rs_pres"]!!.ok) // secretary ≠ president
    }

    @Test fun branchSynonymsCount() {
        val r = roster(
            "Branch Mission Leader",
            "Branch Missionary", "Branch Missionary",
        )
        val byKey = Staffing.gaps(r).associateBy { it.key }
        assertTrue(byKey["wml"]!!.ok)
        assertTrue(byKey["ward_missionaries"]!!.ok)
    }

    @Test fun holdersListNamesTheServingPeople() {
        val r = listOf(
            StaffingMember(position = "Ward Mission Leader", person = "Jane Doe"),
            StaffingMember(position = "Ward Missionary", person = "  "), // blank → not a holder
        )
        val wml = Staffing.gaps(r).first { it.key == "wml" }
        assertEquals(listOf("Jane Doe"), wml.holders)
        val wm = Staffing.gaps(r).first { it.key == "ward_missionaries" }
        assertEquals(1, wm.have)            // counted as held…
        assertTrue(wm.holders.isEmpty())    // …but the blank name is not listed
    }
}
