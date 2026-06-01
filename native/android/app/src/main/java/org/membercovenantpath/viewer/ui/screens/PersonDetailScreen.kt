package org.membercovenantpath.viewer.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.item
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.MenuBook
import androidx.compose.material.icons.filled.AccountBalance
import androidx.compose.material.icons.filled.AssignmentInd
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Diversity3
import androidx.compose.material.icons.filled.EventAvailable
import androidx.compose.material.icons.filled.Flag
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.RadioButtonUnchecked
import androidx.compose.material.icons.filled.School
import androidx.compose.material.icons.filled.Timeline
import androidx.compose.material.icons.filled.VolunteerActivism
import androidx.compose.material.icons.filled.WorkspacePremium
import androidx.compose.material.icons.outlined.Info
import androidx.compose.material.icons.outlined.PeopleOutline
import androidx.compose.material3.AssistChip
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import org.membercovenantpath.viewer.model.Details
import org.membercovenantpath.viewer.model.Member
import org.membercovenantpath.viewer.model.Toggle
import org.membercovenantpath.viewer.model.parsedDetails
import org.membercovenantpath.viewer.ui.components.GoldenHourChips
import org.membercovenantpath.viewer.ui.components.InitialsAvatar
import org.membercovenantpath.viewer.ui.components.PhotoAvatar
import org.membercovenantpath.viewer.ui.components.SectionCard
import org.membercovenantpath.viewer.ui.theme.StatusColors

private val Green = Color(0xFF2E7D32) // green.shade700
private val AmberInfo = Color(0xFFFF8F00) // amber.shade800

/**
 * Full covenant-path detail for one member, laid out like LCR's "new member" record. Driven by
 * `details`; falls back to the flat fields when absent. Ported from person_detail_page.dart.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PersonDetailScreen(member: Member, onBack: () -> Unit) {
    val name = member.name ?: "—"
    val d = member.parsedDetails()

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(name) },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
                    }
                },
            )
        },
    ) { padding ->
        LazyColumn(
            modifier = Modifier.fillMaxWidth().padding(padding),
            contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp),
        ) {
            item { HeaderCard(member, d) }
            item {
                SectionCard(title = "Covenant Path", leadingIcon = Icons.Filled.Timeline) {
                    GoldenHourChips(member = member, highlightNext = true, labeled = true)
                }
            }
            if (d != null) {
                richSections(d, member)
            } else {
                item { FlatFallback(member) }
            }
        }
    }
}

@Composable
private fun HeaderCard(member: Member, d: Details?) {
    val name = member.name ?: "—"
    val memberSince = d?.memberSince ?: member.membershipDuration
    val baptismLine = if (member.isInvestigator) {
        member.baptismGoalDate?.takeIf { it.isNotBlank() }?.let { "Planned baptism $it" }
    } else {
        member.baptismDate?.takeIf { it.isNotBlank() && it != "needs-profile-api" }?.let { "Baptized $it" }
    }
    Box(
        Modifier
            .fillMaxWidth()
            .background(MaterialTheme.colorScheme.primaryContainer, RoundedCornerShape(16.dp))
            .padding(16.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            PhotoAvatar(name = name, photoUrl = member.photoUrl, size = 60.dp)
            Spacer(Modifier.width(16.dp))
            Column {
                Text(
                    name,
                    style = MaterialTheme.typography.titleLarge,
                    fontWeight = FontWeight.Bold,
                    color = MaterialTheme.colorScheme.onPrimaryContainer,
                )
                member.unitName?.takeIf { it.isNotEmpty() }?.let {
                    Text(it, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onPrimaryContainer)
                }
                memberSince?.takeIf { it.isNotEmpty() }?.let {
                    Text(it, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onPrimaryContainer)
                }
                baptismLine?.let {
                    Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onPrimaryContainer)
                }
            }
        }
    }
}

/** All the rich `details`-driven sections (LazyListScope so each is its own item). */
private fun androidx.compose.foundation.lazy.LazyListScope.richSections(d: Details, member: Member) {
    item { SacramentSection(d) }
    item { FriendsSection(d, recordedYes = member.friends == "Yes") }
    item {
        ListTextSection(
            title = "Priesthood Ordination", icon = Icons.Filled.WorkspacePremium,
            lines = d.priesthoodOrdinations, emptyText = "No priesthood ordination on record.",
        )
    }
    item {
        ListTextSection(
            title = "Calling", icon = Icons.Filled.AssignmentInd,
            lines = d.callings, emptyText = "Not yet been given a calling.",
            emptyIsAlert = true, recordedYes = member.calling == "Yes",
        )
    }
    item {
        ListTextSection(
            title = "Ministering Assignment", icon = Icons.Filled.VolunteerActivism,
            lines = d.ministeringAssignments, emptyText = "Not yet received a ministering assignment.",
            recordedYes = member.ministeringAssignment == "Yes",
        )
    }
    item {
        NamesSection(
            title = "Ministering Brothers & Sisters", icon = Icons.Filled.Diversity3,
            names = d.ministeringBrothers + d.ministeringSisters,
            emptyText = "No ministers assigned.",
            recordedYes = member.ministeringBrothersSisters == "Yes",
        )
    }
    item { TempleSection(d) }
    item { PrinciplesSection(d) }
    item { TogglesSection("Self-Reliance Classes Completed", Icons.Filled.School, d.selfReliance) }
    item { TagsSection(d) }
}

@Composable
private fun SacramentSection(d: Details) {
    val all = d.sacrament
    if (all.isEmpty()) return
    var expanded by remember { mutableStateOf(false) }
    val recent = 6
    val shown = (if (expanded) all else all.take(recent)).reversed() // stored newest-first → show oldest→newest
    val missed = d.sacramentMissedCount ?: all.count { !it.attended }

    SectionCard(
        title = "Attended Sacrament Meeting",
        leadingIcon = Icons.Filled.EventAvailable,
        trailing = if (all.size > recent) {
            { TextButton(onClick = { expanded = !expanded }) { Text(if (expanded) "Show recent" else "View all (${all.size})") } }
        } else null,
    ) {
        Column {
            @OptIn(ExperimentalLayoutApi::class)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                shown.forEach { s ->
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        Text(s.label ?: "", style = MaterialTheme.typography.bodySmall)
                        Spacer(Modifier.size(4.dp))
                        AttendanceDot(s.attended)
                    }
                }
            }
            if (missed > 0) {
                Text(
                    "$missed sacrament meeting${if (missed == 1) "" else "s"} missed",
                    color = StatusColors.NoRed,
                    modifier = Modifier.padding(top = 10.dp),
                )
            }
        }
    }
}

@Composable
private fun AttendanceDot(attended: Boolean) {
    Box(
        Modifier
            .size(26.dp)
            .background(if (attended) Green else Color.Transparent, CircleShape)
            .border(1.4.dp, if (attended) Green else StatusColors.GreyBorder, CircleShape),
        contentAlignment = Alignment.Center,
    ) {
        if (attended) Icon(Icons.Filled.Check, contentDescription = null, tint = Color.White, modifier = Modifier.size(16.dp))
    }
}

@Composable
private fun FriendsSection(d: Details, recordedYes: Boolean) {
    SectionCard(title = "Friends in the Church", leadingIcon = Icons.Outlined.PeopleOutline) {
        if (d.friends.isEmpty()) {
            if (recordedYes) RecordedYesNote() else MutedLine("No friends recorded yet.")
        } else {
            Column {
                if (d.friends.any { it.inStake }) {
                    Text("Inside the Stake", style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(bottom = 4.dp))
                }
                d.friends.forEach { f ->
                    Row(Modifier.padding(vertical = 3.dp), verticalAlignment = Alignment.CenterVertically) {
                        InitialsAvatar(name = f.name ?: "?", size = 30.dp)
                        Spacer(Modifier.width(10.dp))
                        Column {
                            Text(f.name ?: "—")
                            f.unit?.takeIf { it.isNotEmpty() }?.let {
                                Text(it, style = MaterialTheme.typography.bodySmall)
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun ListTextSection(
    title: String,
    icon: ImageVector,
    lines: List<String>,
    emptyText: String,
    emptyIsAlert: Boolean = false,
    recordedYes: Boolean = false,
) {
    SectionCard(title = title, leadingIcon = icon) {
        if (lines.isEmpty()) {
            when {
                recordedYes -> RecordedYesNote()
                else -> Text(emptyText, color = if (emptyIsAlert) StatusColors.NoRed else StatusColors.GreyText)
            }
        } else {
            Column { lines.forEach { Text(it, modifier = Modifier.padding(vertical = 2.dp)) } }
        }
    }
}

@Composable
private fun NamesSection(
    title: String,
    icon: ImageVector,
    names: List<String>,
    emptyText: String,
    recordedYes: Boolean = false,
) {
    SectionCard(title = title, leadingIcon = icon) {
        if (names.isEmpty()) {
            if (recordedYes) RecordedYesNote() else MutedLine(emptyText)
        } else {
            Column {
                names.forEach { n ->
                    Row(Modifier.padding(vertical = 3.dp), verticalAlignment = Alignment.CenterVertically) {
                        InitialsAvatar(name = n, size = 28.dp)
                        Spacer(Modifier.width(10.dp))
                        Text(n)
                    }
                }
            }
        }
    }
}

@Composable
private fun TempleSection(d: Details) {
    val experiences = d.templeExperiences.filter { !it.name.isNullOrEmpty() }
    val ordinances = d.templeOrdinances
    if (experiences.isEmpty() && ordinances.isEmpty()) return
    SectionCard(title = "Temple Ordinances and Experiences", leadingIcon = Icons.Filled.AccountBalance) {
        Column {
            experiences.forEach { ToggleRow(it.name ?: "", it.done) }
            if (ordinances.isNotEmpty()) Spacer(Modifier.size(8.dp))
            ordinances.forEach { Text(it, modifier = Modifier.padding(vertical = 2.dp)) }
        }
    }
}

@Composable
private fun PrinciplesSection(d: Details) {
    val lessons = d.lessons
    if (lessons.isEmpty()) return
    SectionCard(
        title = "Principles Taught",
        leadingIcon = Icons.AutoMirrored.Filled.MenuBook,
        trailing = {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Filled.Person, contentDescription = null, tint = Green, modifier = Modifier.size(16.dp))
                Spacer(Modifier.width(4.dp))
                Text("= Member Present", style = MaterialTheme.typography.bodySmall)
            }
        },
    ) {
        Column {
            lessons.forEach { l ->
                Column(Modifier.padding(bottom = 12.dp)) {
                    Text(l.name ?: "", color = Green, fontWeight = FontWeight.Medium)
                    Spacer(Modifier.size(6.dp))
                    @OptIn(ExperimentalLayoutApi::class)
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        l.principles.forEach { p -> PrincipleDot(taught = p.taught, memberPresent = p.memberPresent) }
                    }
                }
            }
        }
    }
}

@Composable
private fun PrincipleDot(taught: Boolean, memberPresent: Boolean) {
    Box(
        Modifier
            .size(22.dp)
            .background(if (taught) Green else Color.Transparent, CircleShape)
            .border(1.4.dp, Green, CircleShape),
        contentAlignment = Alignment.Center,
    ) {
        if (memberPresent) Icon(Icons.Filled.Person, contentDescription = null, tint = if (taught) Color.White else Green, modifier = Modifier.size(13.dp))
    }
}

@Composable
private fun TogglesSection(title: String, icon: ImageVector, items: List<Toggle>) {
    val filtered = items.filter { !it.name.isNullOrEmpty() }
    if (filtered.isEmpty()) return
    SectionCard(title = title, leadingIcon = icon) {
        Column { filtered.forEach { ToggleRow(it.name ?: "", it.done) } }
    }
}

@Composable
private fun ToggleRow(label: String, on: Boolean) {
    Box(
        Modifier
            .fillMaxWidth()
            .padding(vertical = 3.dp)
            .background(
                if (on) Green.copy(alpha = 0.08f) else MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.4f),
                RoundedCornerShape(10.dp),
            )
            .padding(horizontal = 12.dp, vertical = 9.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(
                if (on) Icons.Filled.CheckCircle else Icons.Filled.RadioButtonUnchecked,
                contentDescription = null,
                tint = if (on) Green else StatusColors.GreyBorder,
                modifier = Modifier.size(20.dp),
            )
            Spacer(Modifier.width(10.dp))
            Text(label, fontWeight = if (on) FontWeight.Medium else FontWeight.Normal)
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun TagsSection(d: Details) {
    val tags = d.tags
    if (tags.isEmpty()) return
    SectionCard(title = "Flags", leadingIcon = Icons.Filled.Flag) {
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            tags.forEach { AssistChip(onClick = {}, label = { Text(it) }) }
        }
    }
}

/**
 * When a status field says "Yes" but the (flaky) detail endpoint returned no names, say so rather
 * than "Not yet" — mirrors `_recordedYesNote`.
 */
@Composable
private fun RecordedYesNote() {
    Row(verticalAlignment = Alignment.Top) {
        Icon(Icons.Outlined.Info, contentDescription = null, tint = AmberInfo, modifier = Modifier.size(15.dp))
        Spacer(Modifier.width(6.dp))
        Text(
            "Recorded as yes — names are temporarily unavailable from LCR and will appear once its " +
                "detail data loads on a future sync.",
            color = AmberInfo,
            fontSize = 13.sp,
        )
    }
}

@Composable
private fun MutedLine(text: String) {
    Text(text, color = StatusColors.GreyText)
}

/** Pre-`details` rows: the original flat field list (mirrors `_FlatFallback`). */
@Composable
private fun FlatFallback(member: Member) {
    val fields = listOf(
        "Unit" to member.unitName,
        "Baptism date" to member.baptismDate,
        "Birth date" to member.birthDate,
        "Friends" to member.friends,
        "Aaronic Priesthood" to member.aaronicPriesthood,
        "Melchizedek Priesthood" to member.melchizedekPriesthood,
        "Calling" to member.calling,
        "Ministering brothers/sisters" to member.ministeringBrothersSisters,
        "Ministering assignment" to member.ministeringAssignment,
        "Temple recommend" to member.templeRecommend,
        "Patriarchal blessing" to member.patriarchalBlessing,
        "Living ordinance" to member.livingOrdinance,
    )
    Column(Modifier.padding(top = 8.dp)) {
        fields.forEach { (label, value) ->
            Row(
                Modifier.fillMaxWidth().padding(vertical = 8.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Text(label)
                Text(value ?: "—", fontWeight = FontWeight.Medium)
            }
        }
    }
}
