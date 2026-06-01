package org.membercovenantpath.viewer.ui.screens.tabs

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import org.membercovenantpath.viewer.model.Member
import org.membercovenantpath.viewer.ui.components.PhotoAvatar

/** Bottom sheet listing eligible members still missing a milestone (golden_hour `_showCategory`). */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MissingSheet(
    label: String,
    missing: List<Member>,
    onOpen: (Member) -> Unit,
    onDismiss: () -> Unit,
) {
    ModalBottomSheet(onDismissRequest = onDismiss) {
        Column(Modifier.padding(horizontal = 16.dp).padding(bottom = 24.dp)) {
            Text("Still need: $label", style = MaterialTheme.typography.titleLarge)
            Text(
                "${missing.size} eligible ${if (missing.size == 1) "member" else "members"}",
                style = MaterialTheme.typography.bodySmall,
            )
            HorizontalDivider(Modifier.padding(vertical = 8.dp))
            if (missing.isEmpty()) {
                Box(Modifier.fillMaxWidth().padding(24.dp), contentAlignment = Alignment.Center) {
                    Text("Everyone eligible has this.")
                }
            } else {
                LazyColumn {
                    items(missing, key = { it.personUuid ?: it.name ?: it.hashCode().toString() }) { m ->
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .clickable { onDismiss(); onOpen(m) }
                                .padding(vertical = 8.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            PhotoAvatar(name = m.name ?: "?", photoUrl = m.photoUrl, size = 36.dp)
                            Spacer(Modifier.width(12.dp))
                            Column {
                                Text(m.name ?: "—", fontWeight = FontWeight.Medium)
                                Text(
                                    m.unitName ?: "",
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}
