// Print listing instructions and incoming references for explicit address:length ranges.
// Read-only: does not create functions, disassemble, or change the program.
// @category SmplTrek
// Example: -postScript InspectRanges.java c169c6c0:80 c16ee910:18
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;

public class InspectRanges extends GhidraScript {
    @Override
    protected void run() throws Exception {
        for (String arg : getScriptArgs()) {
            String[] parts = arg.split(":");
            if (parts.length != 2) throw new IllegalArgumentException("Expected hex address:hex length");
            Address start = toAddr(Long.parseUnsignedLong(parts[0].replaceFirst("^0x", ""), 16));
            long length = Long.parseUnsignedLong(parts[1].replaceFirst("^0x", ""), 16);
            if (length <= 0 || length > 0x10000) throw new IllegalArgumentException("Length must be 1..10000 hex");
            Address end = start.add(length - 1);
            println("RANGE " + start + ".." + end);
            var refs = currentProgram.getReferenceManager().getReferencesTo(start);
            while (refs.hasNext()) {
                var ref = refs.next();
                println("REF " + ref.getFromAddress() + " " + ref.getReferenceType());
            }
            var instructions = currentProgram.getListing().getInstructions(start, true);
            while (instructions.hasNext()) {
                var instruction = instructions.next();
                if (instruction.getAddress().compareTo(end) > 0) break;
                println(instruction.getAddress() + " " + instruction.toString());
            }
        }
    }
}
