// Apply classes, vtables and virtual-function names from analysis/rtti_recover.py to a program.
// @category SmplTrek
//
// GUI: Script Manager, add ghidra/scripts as a script directory, run, pick the .rtti.json.
// Headless: -postScript ApplyRttiSymbols.java /path/to/smpltrek-3.2.174.rtti.json
//           (with -scriptPath ghidra/scripts)
//
// Safe to re-run. Before changing anything, it checks that the program matches the JSON: the entry
// point, and that every class type_info in the JSON starts with one of the recorded ABI vptrs.
// It never renames a function or label that a user named by hand; such names get an extra label.
//
// What it creates, all in a Ghidra class namespace per C++ class (nested namespaces follow "::"):
//   typeinfo, typeinfo_name, vtable (secondary vtables: vtable_at_<offset>)   labels and data types
//   vfunc_<slot>                                                               functions (created
//                                                                              and disassembled if absent)
//   aliases (same function in another class's slot)                            extra labels
//   __cxa_pure_virtual_candidate / shared_vfunc_stub_<n>                       global functions

import java.io.File;
import java.io.FileReader;
import java.util.ArrayList;
import java.util.List;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.data.DataType;
import ghidra.program.model.data.DataUtilities;
import ghidra.program.model.data.DataUtilities.ClearDataMode;
import ghidra.program.model.data.IntegerDataType;
import ghidra.program.model.data.PointerDataType;
import ghidra.program.model.data.TerminatedStringDataType;
import ghidra.program.model.data.UnsignedIntegerDataType;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.GhidraClass;
import ghidra.program.model.symbol.Namespace;
import ghidra.program.model.symbol.SourceType;
import ghidra.program.model.symbol.Symbol;
import ghidra.program.model.symbol.SymbolTable;

public class ApplyRttiSymbols extends GhidraScript {
	private SymbolTable symbols;
	private int functionsCreated, functionsRenamed, labelsAdded, failures;

	@Override
	protected void run() throws Exception {
		String[] args = getScriptArgs();
		File file = args.length > 0 ? new File(args[0]) : askFile("RTTI JSON from rtti_recover.py", "Apply");
		JsonObject doc;
		try (FileReader reader = new FileReader(file)) {
			doc = JsonParser.parseReader(reader).getAsJsonObject();
		}
		symbols = currentProgram.getSymbolTable();
		verify(doc);

		JsonArray classes = doc.getAsJsonArray("classes");
		for (JsonElement element : classes) {
			monitor.checkCancelled();
			applyClass(element.getAsJsonObject());
		}
		for (JsonElement element : doc.getAsJsonArray("symbols")) {
			monitor.checkCancelled();
			JsonObject s = element.getAsJsonObject();
			String kind = s.get("kind").getAsString();
			if (kind.equals("virtual_function")) {
				applyVirtualFunction(s);
			}
			else if (kind.equals("shared_virtual_function")) {
				Address address = addr(s.get("address"));
				Function f = ensureFunction(address);
				if (f != null) {
					setFunctionName(f, currentProgram.getGlobalNamespace(), s.get("name").getAsString());
					setPlate(address, "Fresh vtable entry in " + s.get("owned_by_classes").getAsInt() +
						" classes (rtti_recover.py): " + s.get("name").getAsString());
				}
			}
		}
		println(String.format("ApplyRttiSymbols: %d classes, %d functions created, %d renamed, " +
			"%d extra labels, %d failures", classes.size(), functionsCreated, functionsRenamed,
			labelsAdded, failures));
	}

	/** Refuse to touch a program that does not match the JSON. */
	private void verify(JsonObject doc) throws Exception {
		JsonObject source = doc.getAsJsonObject("source");
		Address entry = addr(source.get("entry"));
		boolean entryOk = false;
		for (Address a : symbols.getExternalEntryPointIterator()) {
			entryOk |= a.equals(entry);
		}
		if (!entryOk) {
			throw new IllegalStateException("program entry points do not include " + entry +
				" from " + source.get("file").getAsString() + "; wrong firmware?");
		}
		List<Long> vptrs = new ArrayList<>();
		for (var e : doc.getAsJsonObject("abi").getAsJsonObject("vptrs").entrySet()) {
			vptrs.add(Long.decode(e.getValue().getAsString()));
		}
		int checked = 0;
		for (JsonElement element : doc.getAsJsonArray("classes")) {
			Address ti = addr(element.getAsJsonObject().get("typeinfo"));
			long word = getInt(ti) & 0xffffffffL;
			if (!vptrs.contains(word)) {
				throw new IllegalStateException("type_info at " + ti + " does not start with an ABI vptr");
			}
			checked++;
		}
		println("Verified entry " + entry + " and " + checked + " type_info vptrs for " +
			source.get("file").getAsString() + " (sha256 " + source.get("sha256").getAsString() + ")");
	}

	private void applyClass(JsonObject c) throws Exception {
		String name = c.get("name").getAsString();
		Namespace ns = classNamespace(name);
		Address ti = addr(c.get("typeinfo"));
		label(ti, "typeinfo", ns);
		data(ti, PointerDataType.dataType);
		data(ti.add(4), PointerDataType.dataType);
		Address nameAddress = addr(c.get("name_address"));
		label(nameAddress, "typeinfo_name", ns);
		data(nameAddress, TerminatedStringDataType.dataType);

		StringBuilder bases = new StringBuilder();
		for (JsonElement b : c.getAsJsonArray("bases")) {
			JsonObject base = b.getAsJsonObject();
			bases.append("\n  ").append(base.get("name").isJsonNull() ? "?" : base.get("name").getAsString())
				.append(" at offset ").append(base.get("offset").getAsInt())
				.append(base.get("virtual").getAsBoolean() ? " (virtual)" : "")
				.append(base.get("public").getAsBoolean() ? "" : " (non-public)");
		}
		setPlate(ti, "type_info for " + name + " (" + c.get("kind").getAsString() + ")" +
			(bases.length() > 0 ? "\nBases:" + bases : ""));

		for (JsonElement v : c.getAsJsonArray("vtables")) {
			JsonObject table = v.getAsJsonObject();
			Address start = addr(table.get("address"));
			int top = table.get("offset_to_top").getAsInt();
			label(start, top == 0 ? "vtable" : "vtable_at_" + (-top), ns);
			data(start, IntegerDataType.dataType);
			data(start.add(4), PointerDataType.dataType);
			JsonArray entries = table.getAsJsonArray("entries");
			for (int i = 0; i < entries.size(); i++) {
				Address slot = start.add(8 + 4L * i);
				data(slot, value(entries.get(i)) == 0 ? UnsignedIntegerDataType.dataType : PointerDataType.dataType);
			}
			boolean bounded = table.get("length_bounded_by_children").getAsBoolean();
			setPlate(start, "vtable for " + name + (top == 0 ? "" : " (subobject at offset " + (-top) + ")") +
				", " + entries.size() + " slots" +
				(top == 0 && !bounded ? "\nLength not bounded by a derived class; last slot may be adjacent data." : ""));
		}
	}

	private void applyVirtualFunction(JsonObject s) throws Exception {
		Address address = addr(s.get("address"));
		String full = s.get("name").getAsString();
		List<String> parts = splitQualified(full);
		String leaf = parts.remove(parts.size() - 1);
		Namespace ns = namespaceFor(parts);
		Function f = ensureFunction(address);
		if (f == null) {
			return;
		}
		setFunctionName(f, ns, leaf);
		StringBuilder plate = new StringBuilder("Virtual function " + full);
		JsonArray aliases = s.getAsJsonArray("aliases");
		for (JsonElement a : aliases) {
			List<String> ap = splitQualified(a.getAsString());
			String aliasLeaf = ap.remove(ap.size() - 1);
			label(address, aliasLeaf, namespaceFor(ap));
		}
		if (aliases.size() > 0) {
			plate.append("\nAlso introduced in ").append(aliases.size()).append(" other class slot(s)");
		}
		plate.append("\nIn ").append(s.get("vtable_occurrences").getAsInt()).append(" vtable(s)");
		setPlate(address, plate.toString());
	}

	private Function ensureFunction(Address address) {
		Function f = getFunctionAt(address);
		if (f != null) {
			return f;
		}
		try {
			if (getInstructionAt(address) == null) {
				disassemble(address);
			}
			f = createFunction(address, null);
			if (f != null) {
				functionsCreated++;
				return f;
			}
		}
		catch (Exception e) {
			// fall through to the failure report
		}
		failures++;
		printerr("Could not create a function at " + address);
		return null;
	}

	/** Rename only default or analysis-generated names; otherwise keep the user's name and add a label. */
	private void setFunctionName(Function f, Namespace ns, String name) throws Exception {
		name = sanitize(name);
		Symbol primary = f.getSymbol();
		if (primary.getName().equals(name) && primary.getParentNamespace().equals(ns)) {
			return;
		}
		SourceType source = primary.getSource();
		if (source == SourceType.DEFAULT || source == SourceType.ANALYSIS) {
			f.setParentNamespace(ns);
			f.setName(name, SourceType.IMPORTED);
			functionsRenamed++;
		}
		else {
			label(f.getEntryPoint(), name, ns);
		}
	}

	private void label(Address address, String name, Namespace ns) throws Exception {
		name = sanitize(name);
		if (symbols.getSymbol(name, address, ns) != null) {
			return;
		}
		symbols.createLabel(address, name, ns, SourceType.IMPORTED);
		labelsAdded++;
	}

	private void data(Address address, DataType type) {
		try {
			DataUtilities.createData(currentProgram, address, type, -1, ClearDataMode.CLEAR_ALL_UNDEFINED_CONFLICT_DATA);
		}
		catch (Exception e) {
			// Defined data or instructions already there: leave them.
		}
	}

	private void setPlate(Address address, String text) {
		currentProgram.getListing().setComment(address, ghidra.program.model.listing.CommentType.PLATE, text);
	}

	private Namespace classNamespace(String qualified) throws Exception {
		List<String> parts = splitQualified(qualified);
		String leaf = parts.remove(parts.size() - 1);
		Namespace parent = namespaceFor(parts);
		leaf = sanitize(leaf);
		Namespace existing = symbols.getNamespace(leaf, parent);
		if (existing instanceof GhidraClass) {
			return existing;
		}
		if (existing != null) {
			return symbols.convertNamespaceToClass(existing);
		}
		return symbols.createClass(parent, leaf, SourceType.IMPORTED);
	}

	/** Namespaces for all but the leaf; each level is a class if the JSON has it, else a namespace. */
	private Namespace namespaceFor(List<String> parts) throws Exception {
		Namespace ns = currentProgram.getGlobalNamespace();
		for (String part : parts) {
			String p = sanitize(part);
			Namespace next = symbols.getNamespace(p, ns);
			ns = next != null ? next : symbols.createNameSpace(ns, p, SourceType.IMPORTED);
		}
		return ns;
	}

	/** Split "a::b<c::d>::e" on top-level "::" only (outside <>, (), {}). */
	static List<String> splitQualified(String name) {
		List<String> parts = new ArrayList<>();
		int depth = 0, start = 0;
		for (int i = 0; i < name.length(); i++) {
			char ch = name.charAt(i);
			if (ch == '<' || ch == '(' || ch == '{') depth++;
			else if (ch == '>' || ch == ')' || ch == '}') depth--;
			else if (depth == 0 && ch == ':' && i + 1 < name.length() && name.charAt(i + 1) == ':') {
				parts.add(name.substring(start, i));
				start = i + 2;
				i++;
			}
		}
		parts.add(name.substring(start));
		return parts;
	}

	/** Ghidra symbol names may not contain whitespace. */
	static String sanitize(String name) {
		return name.replaceAll("\\s+", "_");
	}

	private Address addr(JsonElement e) {
		return toAddr(value(e));
	}

	private static long value(JsonElement e) {
		return e.getAsJsonPrimitive().isString() ? Long.decode(e.getAsString()) : e.getAsLong();
	}
}
