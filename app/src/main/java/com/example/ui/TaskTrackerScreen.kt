package com.example.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle

@Composable
fun TaskTrackerScreen(viewModel: TaskViewModel) {
    val solution by viewModel.solution.collectAsStateWithLifecycle()
    val result by viewModel.backendResult.collectAsStateWithLifecycle()
    val verifying by viewModel.isVerifying.collectAsStateWithLifecycle()

    Scaffold { padding ->
        Column(
            modifier = Modifier.fillMaxSize().padding(padding).padding(20.dp).verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(16.dp)
        ) {
            Text("DSG QUBO → Z3 Proof Client", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
            Text(
                "The Android client computes a deterministic local candidate. Formal verification is only claimed after the backend returns a real server-side Z3 response.",
                style = MaterialTheme.typography.bodyMedium
            )

            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Local deterministic candidate", fontWeight = FontWeight.Bold)
                    Text("Configuration: ${solution.configuration}", fontFamily = FontFamily.Monospace)
                    Text("QUBO energy: ${solution.quboEnergy}")
                    Text("Cost: ${solution.totalCost}")
                    Text("Local constraint check: ${if (solution.allConstraintsSatisfied) "SATISFIED" else "VIOLATED"}")
                    Text("Local solution hash: ${solution.solutionHash}", fontFamily = FontFamily.Monospace)
                }
            }

            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                OutlinedButton(onClick = viewModel::recomputeCandidate, enabled = !verifying) { Text("Recompute") }
                Button(onClick = viewModel::verifyWithBackend, enabled = !verifying) { Text(if (verifying) "Calling Z3…" else "Verify with Backend Z3") }
            }

            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Server evidence", fontWeight = FontWeight.Bold)
                    if (result == null) {
                        Text("No backend verification has been run. No proof is fabricated.")
                    } else {
                        Text(result!!.statusMessage)
                        Text("HTTP: ${result!!.httpStatusCode} · Z3: ${result!!.z3Status ?: "NO RESPONSE"}")
                        Text("Proof: ${result!!.proofHash ?: "NONE"}", fontFamily = FontFamily.Monospace)
                        Text("Audit event: ${result!!.auditEventHash ?: "NONE"}", fontFamily = FontFamily.Monospace)
                        if (!result!!.success) Text("The candidate is not formally accepted.", color = MaterialTheme.colorScheme.error)
                    }
                }
            }
            Spacer(Modifier.height(24.dp))
        }
    }
}
