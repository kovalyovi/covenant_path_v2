package org.membercovenantpath.viewer.ui.components

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.SubcomposeAsyncImage
import coil.request.ImageRequest
import androidx.compose.ui.platform.LocalContext

/** Initials from a name ("Smith, John" → "SJ"), mirroring golden_hour.dart `initialsOf`. */
fun initialsOf(name: String): String {
    val parts = name.replace(",", "").trim().split(Regex("\\s+")).filter { it.isNotEmpty() }
    if (parts.isEmpty()) return "?"
    val s = if (parts.size == 1) parts.first().take(1)
    else "${parts.first().take(1)}${parts.last().take(1)}"
    return s.uppercase()
}

private val avatarBg = Color(0xFFC5CAE9)   // indigo.shade100
private val avatarFg = Color(0xFF1A237E)   // indigo.shade900

@Composable
fun InitialsAvatar(name: String, size: Dp = 36.dp, modifier: Modifier = Modifier) {
    Surface(color = avatarBg, shape = CircleShape, modifier = modifier.size(size)) {
        Box(contentAlignment = Alignment.Center) {
            Text(
                text = initialsOf(name),
                color = avatarFg,
                fontWeight = FontWeight.Bold,
                textAlign = TextAlign.Center,
                fontSize = (size.value * 0.36f).sp,
            )
        }
    }
}

/**
 * Member avatar: the stored LCR photo (signed URL) when present, else initials. Falls back to
 * initials while loading / on error too. Mirrors golden_hour.dart `PhotoAvatar`.
 */
@Composable
fun PhotoAvatar(
    name: String,
    photoUrl: String?,
    size: Dp = 36.dp,
    modifier: Modifier = Modifier,
) {
    if (photoUrl.isNullOrEmpty()) {
        InitialsAvatar(name = name, size = size, modifier = modifier)
        return
    }
    val context = LocalContext.current
    SubcomposeAsyncImage(
        model = ImageRequest.Builder(context).data(photoUrl).crossfade(true).build(),
        contentDescription = name,
        contentScale = ContentScale.Crop,
        loading = { InitialsAvatar(name = name, size = size) },
        error = { InitialsAvatar(name = name, size = size) },
        modifier = modifier.size(size).clip(CircleShape),
    )
}
