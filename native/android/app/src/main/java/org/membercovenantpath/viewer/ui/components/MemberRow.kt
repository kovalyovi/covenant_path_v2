package org.membercovenantpath.viewer.ui.components

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.automirrored.filled.StickyNote2
import androidx.compose.material.icons.filled.Event
import androidx.compose.material.icons.filled.WaterDrop
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.compositionLocalOf
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import org.membercovenantpath.viewer.logic.DateParse
import org.membercovenantpath.viewer.logic.NoteSummary
import org.membercovenantpath.viewer.logic.Orgs
import org.membercovenantpath.viewer.model.Member
import org.membercovenantpath.viewer.ui.theme.StatusColors
import org.membercovenantpath.viewer.util.Dates
import java.time.LocalDate

/** person_uuid -> newest leader note; provided by DashboardScaffold so deep list rows (here, the
 *  baptisms timeline, the table) can show note lines without threading the map through props. */
val LocalMemberNotes = compositionLocalOf<Map<String, NoteSummary>> { emptyMap() }

/**
 * One member row. [chips] adds the Golden Hour milestone chips (+ responsibility chip); [showResp]
 * adds just the responsibility chip (Needs view); [showUnit] shows the unit as right-side metadata
 * (else a chevron). [dateField] picks baptism_date vs baptism_goal_date for the date line.
 * Ported from needs_view.dart `_MemberRow`.
 */
@Composable
fun MemberRow(
    member: Member,
    onOpen: (Member) -> Unit,
    modifier: Modifier = Modifier,
    chips: Boolean = false,
    showUnit: Boolean = false,
    showResp: Boolean = false,
    dateField: String = "baptism_date",
    today: LocalDate = LocalDate.now(),
) {
    val name = member.name ?: "—"
    val isBaptism = dateField == "baptism_date"
    val rawDate = if (isBaptism) member.baptismDate else member.baptismGoalDate
    val date = DateParse.parseMemberDate(rawDate)
    val ageLabel = DateParse.ageLabel(member.birthDate, today)
    val resp = if (chips || showResp) Orgs.responsibleParty(member, today) else null
    val subStyle = MaterialTheme.typography.bodySmall
    // #12: on a phone the name takes the whole first row and age drops to the line below (not a
    // cramped second column); inline on wider screens.
    val isMobile = LocalConfiguration.current.screenWidthDp < 600

    Row(
        modifier = modifier
            .fillMaxWidth()
            .clickable { onOpen(member) }
            .padding(horizontal = 4.dp, vertical = 8.dp),
        verticalAlignment = Alignment.Top,
    ) {
        PhotoAvatar(name = name, photoUrl = member.photoUrl, size = 44.dp)
        Spacer(Modifier.width(10.dp))
        Column(Modifier.weight(1f)) {
            if (isMobile || ageLabel == null) {
                Text(name, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
            } else {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(name, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Text("  · $ageLabel", color = StatusColors.GreyText, fontSize = 13.sp)
                }
            }
            if (isMobile && ageLabel != null) {
                Text(ageLabel, color = StatusColors.GreyText, fontSize = 12.5.sp)
            }
            if (date != null) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(
                        if (isBaptism) Icons.Filled.WaterDrop else Icons.Filled.Event,
                        contentDescription = null,
                        tint = if (isBaptism) Color_LightBlue else StatusColors.GreyText,
                        modifier = Modifier.size(13.dp),
                    )
                    Spacer(Modifier.width(4.dp))
                    val text = if (isBaptism) {
                        val ago = DateParse.monthsDaysAgo(date, today)
                        Dates.longMonthDayYear(date) + if (ago.isNotEmpty()) " ($ago)" else ""
                    } else {
                        Dates.fullLong(date)
                    }
                    Text(text, style = subStyle, maxLines = 2, overflow = TextOverflow.Ellipsis)
                }
            }
            if (resp != null) {
                Spacer(Modifier.size(4.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(resp.icon, contentDescription = null, tint = resp.color, modifier = Modifier.size(13.dp))
                    Spacer(Modifier.width(4.dp))
                    Text(resp.label, style = subStyle, color = resp.color)
                }
            }
            LocalMemberNotes.current[member.personUuid]?.let { note ->
                Spacer(Modifier.size(4.dp))
                NoteLine(note)
            }
            if (chips) {
                Spacer(Modifier.size(6.dp))
                GoldenHourChips(member = member, size = 22.dp, highlightNext = true, today = today)
            }
        }
        if (showUnit) {
            Text(
                member.unitName ?: "",
                textAlign = TextAlign.End,
                color = StatusColors.GreyText,
                fontSize = 12.sp,
                modifier = Modifier.width(120.dp),
            )
        } else {
            Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, contentDescription = null)
        }
    }
}

/** The newest leader note under a list row (+N when there are more) — shared by every member list
 *  so notes travel with people in Golden Hour, Needs, and the baptisms timeline. Mirrors the web
 *  `NoteLine` (components/dashboard.tsx). */
@Composable
fun NoteLine(note: NoteSummary) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Icon(
            Icons.AutoMirrored.Filled.StickyNote2,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.primary,
            modifier = Modifier.size(13.dp),
        )
        Spacer(Modifier.width(4.dp))
        Text(
            note.latest,
            style = MaterialTheme.typography.bodySmall,
            fontStyle = FontStyle.Italic,
            color = StatusColors.GreyText,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.weight(1f, fill = false),
        )
        if (note.count > 1) {
            Spacer(Modifier.width(4.dp))
            Text("+${note.count - 1}", style = MaterialTheme.typography.bodySmall, color = StatusColors.GreyText)
        }
    }
}

private val Color_LightBlue = androidx.compose.ui.graphics.Color(0xFF039BE5) // lightBlue.shade600
