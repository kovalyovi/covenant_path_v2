package org.membercovenantpath.viewer.ui.components

import android.content.Intent
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Call
import androidx.compose.material.icons.filled.Email
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.net.toUri
import org.membercovenantpath.viewer.model.Missionary

/**
 * One missionary as a name chip; tapping opens phone/email actions (#12 — the strip's
 * "tap shows phone/email"). Native idiom: a small dialog with tappable tel:/mailto: rows.
 */
@Composable
fun MissionaryChip(m: Missionary) {
    var open by remember { mutableStateOf(false) }
    val context = LocalContext.current
    val c = MaterialTheme.colorScheme

    Surface(
        color = c.primary.copy(alpha = 0.10f),
        shape = RoundedCornerShape(14.dp),
        modifier = Modifier.clip(RoundedCornerShape(14.dp)).clickable { open = true },
    ) {
        Text(
            m.name ?: "",
            color = c.primary,
            fontSize = 12.sp,
            fontWeight = FontWeight.Medium,
            modifier = Modifier.padding(horizontal = 9.dp, vertical = 4.dp),
        )
    }

    if (open) {
        val phone = m.phone?.takeIf { it.isNotBlank() }
        val email = m.email?.takeIf { it.isNotBlank() }
        AlertDialog(
            onDismissRequest = { open = false },
            title = { Text(m.name ?: "Missionary") },
            text = {
                androidx.compose.foundation.layout.Column {
                    if (phone == null && email == null) {
                        Text("No contact details on file.", style = MaterialTheme.typography.bodyMedium)
                    }
                    if (phone != null) {
                        ContactRow(Icons.Filled.Call, phone) {
                            open = false
                            runCatching { context.startActivity(Intent(Intent.ACTION_DIAL, "tel:$phone".toUri())) }
                        }
                    }
                    if (email != null) {
                        ContactRow(Icons.Filled.Email, email) {
                            open = false
                            runCatching { context.startActivity(Intent(Intent.ACTION_SENDTO, "mailto:$email".toUri())) }
                        }
                    }
                }
            },
            confirmButton = { TextButton(onClick = { open = false }) { Text("Close") } },
        )
    }
}

@Composable
private fun ContactRow(icon: androidx.compose.ui.graphics.vector.ImageVector, label: String, onClick: () -> Unit) {
    Row(
        Modifier.clickable(onClick = onClick).padding(vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(icon, contentDescription = null, tint = MaterialTheme.colorScheme.primary, modifier = Modifier.size(18.dp))
        Spacer(Modifier.width(10.dp))
        Text(label)
    }
}
