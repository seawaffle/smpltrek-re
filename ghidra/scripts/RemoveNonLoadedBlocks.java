// Remove memory blocks that are not loaded into the target's address space (use as a -preScript).
// @category SmplTrek
//
// Ghidra's ELF loader creates non-loaded blocks such as _elfHeader, _elfProgramHeaders, .shstrtab.
// ghidra-c6000 v1.2.0's "C6000 Delayed Calls" analyzer throws on them ("Address Overflow in subtract:
// _elfHeader::00000033 - 0x34"), and once it dies, calls are not followed and most code is never
// disassembled (SmplTrek 3.2.174: 13620 instructions instead of the expected hundreds of thousands).

import java.util.ArrayList;
import java.util.List;

import ghidra.app.script.GhidraScript;
import ghidra.program.model.mem.MemoryBlock;

public class RemoveNonLoadedBlocks extends GhidraScript {
	@Override
	protected void run() throws Exception {
		List<MemoryBlock> remove = new ArrayList<>();
		for (MemoryBlock block : currentProgram.getMemory().getBlocks()) {
			if (!block.isLoaded()) {
				remove.add(block);
			}
		}
		for (MemoryBlock block : remove) {
			println("Removing non-loaded block " + block.getName() + " (" + block.getSize() + " bytes)");
			currentProgram.getMemory().removeBlock(block, monitor);
		}
	}
}
