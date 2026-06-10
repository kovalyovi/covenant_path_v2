package org.membercovenantpath.viewer.logic

import kotlinx.serialization.json.add
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
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
            familyNamePrepared = "Yes", firstTempleVisit = "Yes",
        )
        assertEquals(1.0, Milestones.avgCompletion(listOf(complete), today), 1e-9)

        // Same person missing exactly one of eight eligible milestones → 7/8.
        val missingOne = complete.copy(calling = "No")
        assertEquals(7.0 / 8.0, Milestones.avgCompletion(listOf(missingOne), today), 1e-9)
    }

    // --- detail-view eligibility + Needs categories (status-sections work) ---

    @Test fun endowmentDisplayGatesIneligibleToNA() {
        // Adult, member 1yr+ → eligible: a "No" stays "No".
        assertEquals("No", Milestones.endowmentDisplay(
            Member(birthDate = "1990-01-01", baptismDate = "2023-01-01", livingOrdinance = "No"), today))
        // <1-year member → ineligible: "No" becomes "N/A".
        assertEquals("N/A", Milestones.endowmentDisplay(
            Member(birthDate = "1990-01-01", baptismDate = "2026-02-01", livingOrdinance = "No"), today))
        // A real "Yes" is always kept.
        assertEquals("Yes", Milestones.endowmentDisplay(Member(birthDate = "2015", livingOrdinance = "Yes"), today))
    }

    @Test fun completionOfIsEligibleOnlyFraction() {
        // Adult female, member 1yr+ → applicable: Friends, Calling, Has-ministers,
        // Ministering-assignment, Family name, First temple visit.
        val none = Member(sex = "F", birthDate = "1990-01-01", baptismDate = "2023-01-01")
        assertEquals(0.0, Milestones.completionOf(none, today), 1e-9)
        val allDone = none.copy(
            friends = "Yes", calling = "Yes", ministeringBrothersSisters = "Yes", ministeringAssignment = "Yes",
            familyNamePrepared = "Yes", firstTempleVisit = "Yes",
        )
        assertEquals(1.0, Milestones.completionOf(allDone, today), 1e-9)
    }

    // --- Temple Ordinances and Experiences (family name + first temple visit) ---

    @Test fun templeExperiencesEligibleAt12LikeCalling() {
        val fn = ms("Family name prepared")
        val ft = ms("First temple visit")
        assertTrue(fn.eligible(Member(birthDate = "2014"), today))  // turns 12 in 2026
        assertTrue(ft.eligible(Member(birthDate = "2014"), today))
        assertFalse(fn.eligible(Member(birthDate = "2018"), today)) // a child is not eligible
        assertFalse(ft.eligible(Member(birthDate = "2018"), today))
    }

    @Test fun templeExperienceFlatColumnWinsAndDetailsFallback() {
        // Flat column (filled by the daily sync) wins.
        assertEquals("Yes", Milestones.firstTempleVisitValue(Member(firstTempleVisit = "Yes")))
        // Sentinel flat value falls back to details.templeExperiences (same LCR commitments).
        val details = buildJsonObject {
            put("templeExperiences", buildJsonArray {
                add(buildJsonObject { put("name", "Prepare a Family Name for the Temple"); put("done", false) })
                add(buildJsonObject { put("name", "Perform Baptisms for Deceased Ancestors"); put("done", true) })
            })
        }
        val m = Member(birthDate = "2006", firstTempleVisit = "needs-profile-api", details = details)
        assertEquals("Yes", Milestones.firstTempleVisitValue(m))
        assertEquals("No", Milestones.familyNameValue(m))
    }

    @Test fun templeExperienceDisplayGatesIneligibleToNA() {
        // Under-12 "No" displays as N/A (can't do proxy baptisms yet); a real "Yes" is kept.
        assertEquals("N/A", Milestones.firstTempleVisitDisplay(
            Member(birthDate = "2018", firstTempleVisit = "No"), today))
        assertEquals("Yes", Milestones.firstTempleVisitDisplay(
            Member(birthDate = "2018", firstTempleVisit = "Yes"), today))
        assertEquals("No", Milestones.familyNameDisplay(
            Member(birthDate = "2006", familyNamePrepared = "No"), today))
    }

    @Test fun needsCategoriesAddLongerHorizonCovenants() {
        val labels = Milestones.needsCategories.map { it.label }
        assertTrue("Temple Recommend" in labels)
        assertTrue("Endowment" in labels)
        assertTrue("Patriarchal Blessing" in labels)
        val en = Milestones.needsCategories.first { it.label == "Endowment" }
        // Eligible adult 1yr+ with no living ordinance is "missing" endowment.
        val adult = Member(birthDate = "1990-01-01", baptismDate = "2023-01-01", livingOrdinance = "No")
        assertTrue(en.eligible(adult, today) && !en.complete(adult))
        assertFalse(en.eligible(Member(birthDate = "2018"), today)) // a child is not eligible
    }
}
