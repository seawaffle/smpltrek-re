// Disable named auto-analyzers before analysis runs (use as a headless -preScript).
// @category SmplTrek
//
// Headless: -preScript DisableAnalyzers.java "C6000 Register Branch Flow" "C6000 Late Branch Flow"
//
// On SmplTrek 3.2.174 (ghidra-c6000 v1.2.0, Ghidra 12.1.4) those two analyzers took 2699 s and
// 2443 s of a 5400 s run that then timed out, and a timed-out headless run saves none of its
// analysis. All other analyzers together took about 4 minutes.

import ghidra.app.script.GhidraScript;

public class DisableAnalyzers extends GhidraScript {
	@Override
	protected void run() throws Exception {
		for (String name : getScriptArgs()) {
			setAnalysisOption(currentProgram, name, "false");
			println("Disabled analyzer: " + name);
		}
	}
}
