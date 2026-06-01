package org.membercovenantpath.viewer.logic

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.membercovenantpath.viewer.model.Member
import java.time.LocalDate

/** Verifies milestone eligibility + completion match golden_hour.dart exactly. */
class MilestonesTest {

    private val today = LocalDate.of(2026, 5, 31)

    private fun ms(label: String) = Milestones.all.first { it.label == label }

    @Test fun friendsAppliesToEveryoneAndChecksYes() {
        val friend = ms("Friends")
        assertTrue(friend.eligible(Member(birthDate = null), today))
        assertTrue(friend.complete(Member(friends = "Yes")))
        assertFalse(friend.complete(Member(friends = "No")))
        // sentinel is not "Yes" → incomplete (unknown), matching the == 'Yes' rule.
        assertFalse(friend.complete(Member(friends = "needs-profile-api")))
    }

    @Test fun callingEligibleWhenTurns12ThisYear() {
        val calling = ms("Calling")
        assertTrue(calling.eligible(Member(birthDate = "2014"), today))  // turns 12 in 2026
        assertFalse(calling.eligible(Member(birthDate = "2015"), today)) // turns 11
        assertFalse(calling.eligible(Member(birthDate = null), today))   // unknown → not eligible
    }

    @Test fun ministeringAssignmentEligibleAt14() {
        val ma = ms("Ministering assignment")
        assertTrue(ma.eligible(Member(birthDate = "2012"), today))  // turns 14
        assertFalse(ma.eligible(Member(birthDate = "2013"), today)) // turns 13
    }

    @Test fun aaronicRequiresMaleAndTurns12() {
        val ap = ms("Aaronic Priesthood")
        assertTrue(ap.eligible(Member(sex = "M", birthDate = "2014"), today))
        assertFalse(ap.eligible(Member(sex = "F", birthDate = "2014"), today)) // female
        assertFalse(ap.eligible(Member(sex = "M", birthDate = "2016"), today)) // turns 10
    }

    @Test fun melchizedekRequiresMaleAge18AndMemberOneYear() {
        val mp = ms("Melchizedek Priesthood")
        // Male, 30 now (full birthdate), baptized 400 days ago → eligible.
        assertTrue(mp.eligible(Member(sex = "M", birthDate = "1996-01-01", baptismDate = "2025-04-26"), today))
        // Female → not eligible.
        assertFalse(mp.eligible(Member(sex = "F", birthDate = "1996-01-01", baptismDate = "2025-04-26"), today))
        // Male, 18+, but member <1 year → not eligible.
        assertFalse(mp.eligible(Member(sex = "M", birthDate = "1996-01-01", baptismDate = "2026-02-01"), today))
        // Male, member 1yr+, but only 17 now → not eligible.
        assertFalse(mp.eligible(Member(sex = "M", birthDate = "2009-12-31", baptismDate = "2024-01-01"), today))
    }

    @Test fun forMemberFiltersToEligibleOnly() {
        // A 10-year-old girl: only Friends + Has ministers (the everyone milestones) apply.
        val child = Member(sex = "F", birthDate = "2016")
        val labels = Milestones.forMember(child, today).map { it.label }.toSet()
        assertEquals(setOf("Friends", "Has ministers"), labels)
    }

    @Test fun avgCompletionIsEligibleOnly() {
        // One adult male, member 1yr+, with everything done → 100%.
        val complete = Member(
            sex = "M", birthDate = "1990-01-01", baptismDate = "2024-01-01",
            friends = "Yes", calling = "Yes", ministeringBrothersSisters = "Yes",
            ministeringAssignment = "Yes", aaronicPriesthood = "Yes", melchizedekPriesthood = "Yes",
        )
        assertEquals(1.0, Milestones.avgCompletion(listOf(complete), today), 1e-9)

        // Same person missing exactly one of six eligible milestones → 5/6.
        val missingOne = complete.copy(calling = "No")
        assertEquals(5.0 / 6.0, Milestones.avgCompletion(listOf(missingOne), today), 1e-9)
    }
}
