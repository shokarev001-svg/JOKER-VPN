package com.v2ray.ang.ui.main

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.AbsoluteAlignment
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.currentStateAsState
import coil3.compose.AsyncImage
import com.v2ray.ang.R
import com.v2ray.ang.util.LogUtil

/** Decorative art only. The service state controls the expression; no simulated connection. */
@Composable
internal fun JokerPortrait(running: Boolean, accent: Color) {
    val lifecycle by LocalLifecycleOwner.current.lifecycle.currentStateAsState()
    val moving = running && lifecycle.isAtLeast(Lifecycle.State.RESUMED)
    val smile by animateFloatAsState(
        targetValue = if (running) 1f else 0f,
        animationSpec = tween(650), label = "jokerSmile",
    )
    // Removing the transition while stopped/backgrounded avoids a permanent frame loop.
    val breath = if (moving) jokerBreathing() else 0f
    Box(Modifier.fillMaxWidth().height(286.dp).clearAndSetSemantics { },
        contentAlignment = Alignment.Center) {
        Box(Modifier.size(278.dp).clip(RoundedCornerShape(34.dp))) {
            Box(Modifier.matchParentSize().graphicsLayer {
                scaleX = 1f + breath * .025f
                scaleY = scaleX
                rotationZ = breath * .8f
                translationY = -breath * 3.dp.toPx()
            }) {
                // One atlas, two square frames. Coil owns asynchronous decoding and request
                // cancellation on leaving composition; both expressions share its memory cache.
                AsyncImage(
                    model = R.drawable.joker_portrait_atlas,
                    contentDescription = null,
                    contentScale = ContentScale.Crop,
                    alignment = AbsoluteAlignment.CenterLeft,
                    placeholder = painterResource(R.drawable.joker_emblem),
                    error = painterResource(R.drawable.joker_emblem),
                    onError = { LogUtil.w("JokerPortrait", "Decode idle portrait failed", it.result.throwable) },
                    modifier = Modifier.matchParentSize(),
                )
                AsyncImage(
                    model = R.drawable.joker_portrait_atlas,
                    contentDescription = null,
                    contentScale = ContentScale.Crop,
                    alignment = AbsoluteAlignment.CenterRight,
                    error = painterResource(R.drawable.joker_emblem),
                    onError = { LogUtil.w("JokerPortrait", "Decode active portrait failed", it.result.throwable) },
                    modifier = Modifier.matchParentSize().graphicsLayer { alpha = smile },
                )
            }
            Box(Modifier.matchParentSize().background(Brush.verticalGradient(
                0f to Color.Transparent, .72f to Color.Transparent, 1f to Color(0xFF100D1C))))
        }
        if (moving) JokerLaughter(accent)
    }
}

@Composable
private fun jokerBreathing(): Float {
    val transition = rememberInfiniteTransition(label = "jokerBreathing")
    val breath by transition.animateFloat(
        initialValue = 0f, targetValue = 1f,
        animationSpec = infiniteRepeatable(tween(2100), RepeatMode.Reverse), label = "breath",
    )
    return breath
}

@Composable
private fun JokerLaughter(accent: Color) {
    val transition = rememberInfiniteTransition(label = "jokerLaughter")
    val progress by transition.animateFloat(
        initialValue = 0f, targetValue = 1f,
        animationSpec = infiniteRepeatable(tween(3600, easing = LinearEasing)), label = "laughRise",
    )
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        repeat(3) { index ->
            val phase = (progress - index * .17f) / .55f
            Text(stringResource(R.string.joker_laugh), color = accent,
                fontSize = (15 + index * 2).sp, fontWeight = FontWeight.Black,
                modifier = Modifier.graphicsLayer {
                    alpha = if (phase > 0f && phase < 1f) (1f - phase) * .85f else 0f
                    translationX = ((index - 1) * 64).dp.toPx() * phase.coerceIn(0f, 1f)
                    translationY = (-25 - 105 * phase.coerceIn(0f, 1f)).dp.toPx()
                    rotationZ = (index - 1) * 16f
                    scaleX = .85f + phase.coerceIn(0f, 1f) * .3f
                    scaleY = scaleX
                })
        }
    }
}
