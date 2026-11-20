// Print the instruction listing between two addresses: -postScript ListRange.java START END
// @category SmplTrek
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Instruction;

public class ListRange extends GhidraScript {
	@Override
	protected void run() throws Exception {
		String[] a = getScriptArgs();
		for (int k = 0; k + 1 < a.length; k += 2) {
			Address start = toAddr(Long.parseUnsignedLong(a[k].replaceFirst("^0x", ""), 16));
			Address end = toAddr(Long.parseUnsignedLong(a[k + 1].replaceFirst("^0x", ""), 16));
			if (getInstructionAt(start) == null) disassemble(start);
			Instruction i = getInstructionAt(start);
			if (i == null) i = getInstructionAfter(start);
			println("LISTING " + start + " - " + end);
			while (i != null && i.getAddress().compareTo(end) < 0) {
				println("L " + i.getAddress() + "  " + i.toString());
				i = i.getNext();
			}
		}
	}
}
