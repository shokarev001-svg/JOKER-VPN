package com.v2ray.ang.ui.main

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.BorderStroke
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
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.v2ray.ang.R

private val JokerInk = Color(0xFF090B11)
private val JokerGold = Color(0xFFD9AE58)

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

    val state by mainViewModel.uiState.collectAsStateWithLifecycle()
    val hasProfile = !state.selectedGuid.isNullOrEmpty()
    val running = state.isRunning
    Column(
        modifier = Modifier.fillMaxSize()
            .background(Brush.verticalGradient(listOf(JokerInk, Color(0xFF182032), JokerInk)))
            .safeDrawingPadding()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 24.dp, vertical = 32.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(22.dp),
    ) {
        Text(stringResource(R.string.app_name), color = JokerGold, fontSize = 34.sp,
            fontWeight = FontWeight.Black, letterSpacing = 3.sp, textAlign = TextAlign.Center)
        Spacer(Modifier.height(16.dp))
        Button(
            onClick = { onAction(MainAction.ToggleService) },
            enabled = hasProfile || running,
            shape = CircleShape,
            modifier = Modifier.size(220.dp),
            border = BorderStroke(3.dp, JokerGold),
            contentPadding = PaddingValues(24.dp),
            colors = ButtonDefaults.buttonColors(
                containerColor = if (running) Color(0xFF4D3820) else Color(0xFF1C212B),
                contentColor = JokerGold,
                disabledContainerColor = Color(0xFF171B25),
                disabledContentColor = Color(0xFFA4A8B3),
            ),
        ) {
            Column(horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(16.dp)) {
                Icon(painterResource(if (running) R.drawable.ic_stop_24dp else R.drawable.ic_play_24dp),
                    contentDescription = null, modifier = Modifier.size(64.dp))
                Text(stringResource(if (running) R.string.acc_stop else R.string.acc_start),
                    textAlign = TextAlign.Center, fontWeight = FontWeight.Bold)
            }
        }
        Surface(shape = RoundedCornerShape(18.dp), color = Color(0xFF171B25),
            border = BorderStroke(1.dp, Color(0xFF333845))) {
            Text(
                if (hasProfile || running) mainViewModel.formatStatus(state.status)
                else stringResource(R.string.title_file_chooser),
                modifier = Modifier.fillMaxWidth().padding(20.dp),
                color = Color.White, textAlign = TextAlign.Center,
            )
        }
        Button(onClick = { onAction(MainAction.TestCurrentServer) }, enabled = running,
            modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(14.dp),
            colors = ButtonDefaults.buttonColors(containerColor = JokerGold, contentColor = JokerInk)) {
            Text(stringResource(R.string.connection_test_pending))
        }
        OutlinedButton(onClick = { onAction(MainAction.ImportClipboard) },
            modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(14.dp),
            border = BorderStroke(1.dp, JokerGold)) {
            Text(stringResource(R.string.menu_item_import_config_clipboard), color = JokerGold)
        }
        OutlinedButton(onClick = { advanced = true }, modifier = Modifier.fillMaxWidth(),
            shape = RoundedCornerShape(14.dp)) {
            Text(stringResource(R.string.title_server), color = JokerGold)
        }
        TextButton(onClick = { onNavigate(MainDestination.Settings) }) {
            Text(stringResource(R.string.title_settings), color = Color(0xFFD1D5DE))
        }
    }
}
