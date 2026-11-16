package com.v2ray.ang.ui.main

import androidx.activity.compose.BackHandler
import androidx.activity.compose.LocalActivity
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.view.WindowCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.v2ray.ang.R

private val JokerInk = Color(0xFF100D1C)
private val JokerGold = Color(0xFFF1CE8B)
private val JokerLilac = Color(0xFFBB9AFF)
private val JokerMint = Color(0xFF63E3B8)
private val JokerWhite = Color(0xFFF5F0FF)
private val JokerMuted = Color(0xFFC3B9D7)

/** Presentation only: MainActivity retains permission, import and service ownership. */
@Composable
fun JokerEntryScreen(
    mainViewModel: MainViewModel,
    onAction: (MainAction) -> Unit,
    onNavigate: (MainDestination) -> Unit,
) {
    var advanced by rememberSaveable { mutableStateOf(false) }
    BackHandler(enabled = advanced) { advanced = false }
    if (advanced) {
        Column(Modifier.fillMaxSize()) {
            TextButton(onClick = { advanced = false }) {
                Text(stringResource(R.string.acc_back))
            }
            Box(Modifier.weight(1f)) {
                MainScreen(mainViewModel, onAction, onNavigate)
            }
        }
        return
    }

    // The home artwork is always dark; restore the user's bar appearance on leaving it.
    val activity = LocalActivity.current
    val view = LocalView.current
    DisposableEffect(activity, view) {
        val controller = activity?.let { WindowCompat.getInsetsController(it.window, view) }
        val previousStatus = controller?.isAppearanceLightStatusBars
        val previousNavigation = controller?.isAppearanceLightNavigationBars
        controller?.isAppearanceLightStatusBars = false
        controller?.isAppearanceLightNavigationBars = false
        onDispose {
            if (previousStatus != null) controller?.isAppearanceLightStatusBars = previousStatus
            if (previousNavigation != null) controller?.isAppearanceLightNavigationBars = previousNavigation
        }
    }

    val state by mainViewModel.uiState.collectAsStateWithLifecycle()
    val hasProfile = !state.selectedGuid.isNullOrEmpty()
    val running = state.isRunning
    val accent by animateColorAsState(
        if (running) JokerMint else JokerLilac, animationSpec = tween(450), label = "connectionAccent"
    )
    Box(Modifier.fillMaxSize().background(JokerInk)) {
        // Decorative suits and a soft glow are vector artwork, with no accessibility action.
        Canvas(Modifier.matchParentSize()) {
            drawCircle(Brush.radialGradient(listOf(Color(0xFF462562), Color.Transparent),
                center = Offset(size.width * .85f, size.height * .18f), radius = size.width * .9f),
                radius = size.width * .9f, center = Offset(size.width * .85f, size.height * .18f))
            drawCircle(Brush.radialGradient(listOf(Color(0xFF173E3B), Color.Transparent),
                center = Offset(0f, size.height * .7f), radius = size.width * .8f),
                radius = size.width * .8f, center = Offset(0f, size.height * .7f))
            for ((x, y) in listOf(.12f to .18f, .88f to .4f, .08f to .61f)) {
                val cx = size.width * x
                val cy = size.height * y
                val r = 9.dp.toPx()
                val diamond = Path().apply {
                    moveTo(cx, cy - r); lineTo(cx + r * .6f, cy)
                    lineTo(cx, cy + r); lineTo(cx - r * .6f, cy); close()
                }
                drawPath(diamond, JokerGold.copy(alpha = .16f))
            }
        }
        Column(
            modifier = Modifier.fillMaxSize().safeDrawingPadding()
                .verticalScroll(rememberScrollState()).padding(horizontal = 24.dp, vertical = 20.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(18.dp),
        ) {
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Icon(painterResource(R.drawable.joker_emblem), contentDescription = null,
                    tint = Color.Unspecified, modifier = Modifier.size(42.dp))
                Spacer(Modifier.width(12.dp))
                Text(stringResource(R.string.app_name), color = JokerWhite,
                    fontWeight = FontWeight.Black, letterSpacing = 2.sp,
                    fontSize = 22.sp, modifier = Modifier.weight(1f))
                IconButton(onClick = { onNavigate(MainDestination.Settings) },
                    modifier = Modifier.size(48.dp).background(Color(0xFF2B223B), CircleShape)) {
                    Icon(painterResource(R.drawable.ic_settings_24dp),
                        contentDescription = stringResource(R.string.title_settings), tint = JokerGold)
                }
            }
            Text(stringResource(R.string.joker_tagline), color = JokerMuted,
                fontSize = 15.sp, textAlign = TextAlign.Center)
            Surface(color = accent.copy(alpha = .12f), shape = RoundedCornerShape(50),
                border = BorderStroke(1.dp, accent.copy(alpha = .35f))) {
                Row(Modifier.padding(horizontal = 16.dp, vertical = 9.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Box(Modifier.size(7.dp).background(accent, CircleShape))
                    Text(stringResource(when {
                        running -> R.string.joker_running
                        hasProfile -> R.string.joker_ready
                        else -> R.string.title_file_chooser
                    }), color = accent, fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
                }
            }
            JokerPortrait(running = running, accent = accent)
            OutlinedButton(onClick = { onAction(MainAction.OpenMembership) },
                modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp),
                colors = ButtonDefaults.outlinedButtonColors(contentColor = JokerGold)) {
                Text(stringResource(R.string.joker_membership_title))
            }
            Button(
                onClick = { onAction(MainAction.ToggleService) },
                enabled = hasProfile || running,
                modifier = Modifier.fillMaxWidth().heightIn(min = 60.dp),
                shape = RoundedCornerShape(20.dp),
                colors = ButtonDefaults.buttonColors(
                    containerColor = if (running) JokerMint else JokerGold,
                    contentColor = JokerInk,
                    disabledContainerColor = Color(0xFF3B3249),
                    disabledContentColor = Color(0xFFC0B4D1),
                ),
                contentPadding = PaddingValues(horizontal = 20.dp, vertical = 18.dp),
            ) {
                Icon(painterResource(if (running) R.drawable.ic_stop_24dp else R.drawable.ic_play_24dp),
                    contentDescription = null, modifier = Modifier.size(22.dp))
                Spacer(Modifier.width(10.dp))
                Text(stringResource(if (running) R.string.joker_disconnect else R.string.joker_connect),
                    fontSize = 17.sp, fontWeight = FontWeight.Bold, textAlign = TextAlign.Center)
            }
            Surface(shape = RoundedCornerShape(24.dp), color = Color(0xFF241E33),
                border = BorderStroke(1.dp, Color(0xFF443652)), modifier = Modifier.fillMaxWidth()) {
                Column(Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    Text(
                        if (hasProfile || running) mainViewModel.formatStatus(state.status)
                        else stringResource(R.string.title_file_chooser),
                        color = JokerWhite, fontSize = 14.sp, lineHeight = 21.sp,
                    )
                    OutlinedButton(onClick = { onAction(MainAction.TestCurrentServer) }, enabled = running,
                        modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp),
                        border = BorderStroke(1.dp, if (running) JokerMint.copy(alpha = .5f) else Color(0xFF50445F)),
                        shape = RoundedCornerShape(14.dp),
                        colors = ButtonDefaults.outlinedButtonColors(contentColor = JokerMint,
                            disabledContentColor = Color(0xFFA89BB9))) {
                        Text(stringResource(R.string.connection_test_pending), textAlign = TextAlign.Center)
                    }
                }
            }
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                OutlinedButton(onClick = { advanced = true },
                    modifier = Modifier.weight(1f).heightIn(min = 56.dp),
                    shape = RoundedCornerShape(18.dp), border = BorderStroke(1.dp, JokerLilac.copy(alpha = .4f)),
                    colors = ButtonDefaults.outlinedButtonColors(contentColor = JokerWhite)) {
                    Text(stringResource(R.string.title_server), textAlign = TextAlign.Center)
                }
                OutlinedButton(onClick = { onAction(MainAction.ImportClipboard) },
                    modifier = Modifier.weight(1f).heightIn(min = 56.dp),
                    shape = RoundedCornerShape(18.dp), border = BorderStroke(1.dp, JokerGold.copy(alpha = .4f)),
                    colors = ButtonDefaults.outlinedButtonColors(contentColor = JokerGold)) {
                    Text(stringResource(R.string.menu_item_import_config_clipboard),
                        textAlign = TextAlign.Center, fontSize = 12.sp)
                }
            }
        }
    }
}
