// Print program statistics, then decompile the function containing each given address.
// @category SmplTrek
//
// Headless: -postScript DecompileAt.java c1666dac c15d3240 ...   (hex, with or without 0x)
// With no arguments it prints only the statistics. Creates a function at an address that has
// instructions but no function, so a known entry can be inspected before analysis finds it.

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;

public class DecompileAt extends GhidraScript {
	@Override
	protected void run() throws Exception {
		var listing = currentProgram.getListing();
		println(String.format("STATS functions=%d instructions=%d defined_data=%d",
			currentProgram.getFunctionManager().getFunctionCount(),
			listing.getNumInstructions(), listing.getNumDefinedData()));

		DecompInterface decompiler = new DecompInterface();
		decompiler.openProgram(currentProgram);
		for (String arg : getScriptArgs()) {
			Address address = toAddr(Long.parseUnsignedLong(arg.replaceFirst("^0x", ""), 16));
			Function f = getFunctionContaining(address);
			if (f == null && getInstructionAt(address) == null) {
				// Code that analysis did not reach. Only safe after auto-analysis has run (the
				// ghidra-c6000 packet analyzer must have primed the decode context first).
				disassemble(address);
			}
			if (f == null && getInstructionAt(address) != null) {
				f = createFunction(address, null);
			}
			if (f == null) {
				println("NOFUNC " + address + (getInstructionAt(address) == null ? " (no instruction)" : ""));
				continue;
			}
			DecompileResults result = decompiler.decompileFunction(f, 120, monitor);
			println("==== " + address + " in " + f.getName(true) + " @ " + f.getEntryPoint() +
				" size " + f.getBody().getNumAddresses());
			if (result.decompileCompleted()) {
				println(result.getDecompiledFunction().getC());
			}
			else {
				println("DECOMPILE FAILED: " + result.getErrorMessage());
			}
		}
		decompiler.dispose();
	}
}
