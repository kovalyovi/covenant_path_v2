package org.membercovenantpath.viewer.logic

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import org.membercovenantpath.viewer.model.Member
import java.time.LocalDate

/** Verifies org ownership matches golden_hour.dart `responsibleOrg`. */
class OrgsTest {

    private val today = LocalDate.of(2026, 5, 31)

    @Test fun noBaptismDateIsUnassigned() {
        assertNull(Orgs.responsibleOrg(Member(baptismDate = null), today))
        assertNull(Orgs.responsibleOrg(Member(baptismDate = "needs-profile-api"), today))
        assertEquals("Unassigned", Orgs.responsibleParty(Member(baptismDate = null), today).label)
    }

    @Test fun firstYearIsWml() {
        // ~3 months ago → < 12 months → WML, regardless of sex.
        assertEquals(OrgBucket.WML, Orgs.responsibleOrg(Member(sex = "M", baptismDate = "2026-03-01"), today))
        assertEquals(OrgBucket.WML, Orgs.responsibleOrg(Member(sex = "F", baptismDate = "2026-03-01"), today))
    }

    @Test fun afterAYearSplitsBySex() {
        // ~2 years ago → ≥12 months → EQ (men) / RS (women).
        assertEquals(OrgBucket.EQ, Orgs.responsibleOrg(Member(sex = "M", baptismDate = "2024-01-01"), today))
        assertEquals(OrgBucket.RS, Orgs.responsibleOrg(Member(sex = "F", baptismDate = "2024-01-01"), today))
    }

    @Test fun boundaryAtTwelveMonths() {
        // Exactly ~12 months (366 days → 12.0 months via /30.44 floor = 12) → past WML into EQ/RS.
        val twelveMonthsAgo = today.minusDays(366)
        assertEquals(OrgBucket.EQ, Orgs.responsibleOrg(Member(sex = "M", baptismDate = twelveMonthsAgo.toString()), today))
    }
}
