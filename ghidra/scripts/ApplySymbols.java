// Apply a sonicware-symbols/1 file (symbols/<product>-<version>.json) to a program: function and
// data names, with confidence, prototype, type and evidence as plate comments.
// @category SmplTrek
//
// GUI: Script Manager, add ghidra/scripts as a script directory, run, pick the JSON.
// Headless: -postScript ApplySymbols.java /path/to/smpltrek-3.2.174.json [min=probable] [signatures]
//           (with -scriptPath ghidra/scripts)
//
// Options (after the path, any order):
//   min=confirmed|probable|speculative   skip entries below this confidence (default: speculative, all)
//   signatures                           also apply the prototypes as function signatures (off by
//                                        default; see "Signatures" below)
//
// Safe to re-run. Before changing anything, it checks every function entry's "prefix_sha256" (SHA-256 of
// the first 16 bytes at the address, first 128 bits; analysis/symfile.py, the same check as
// analysis/test_symbols.py) against the program's memory and stops
// on any mismatch, so a file for another firmware or version cannot be applied.
// Like ApplyRttiSymbols.java, it never renames a function or label that a user named by hand; such
// names get an extra label instead. Its plate comment block starts with the line "[sonicware-symbols]";
// text above that line (for example the RTTI plate) is kept, the block itself is replaced on re-run.
//
// Signatures: the prototypes in the JSON are notes, not C (they use "?" for an unread argument, register
// comments, and types that exist only as names). With "signatures", each prototype is reduced to what
// is certain: "?" becomes undefined4, a pointer to an unknown type becomes a pointer to an empty
// placeholder structure of that name (category /sonicware), any other unknown type becomes undefined4,
// function pointers become void *, and a parameter named "this" is renamed "self". Only prototypes that
// reduce cleanly are applied; the rest are counted and listed.

import java.io.File;
import java.io.FileReader;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import ghidra.app.cmd.function.ApplyFunctionSignatureCmd;
import ghidra.app.cmd.function.FunctionRenameOption;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.data.BooleanDataType;
import ghidra.program.model.data.CategoryPath;
import ghidra.program.model.data.CharDataType;
import ghidra.program.model.data.DataType;
import ghidra.program.model.data.DataTypeConflictHandler;
import ghidra.program.model.data.DataTypeManager;
import ghidra.program.model.data.DoubleDataType;
import ghidra.program.model.data.FloatDataType;
import ghidra.program.model.data.FunctionDefinitionDataType;
import ghidra.program.model.data.IntegerDataType;
import ghidra.program.model.data.LongLongDataType;
import ghidra.program.model.data.ParameterDefinition;
import ghidra.program.model.data.ParameterDefinitionImpl;
import ghidra.program.model.data.PointerDataType;
import ghidra.program.model.data.ShortDataType;
import ghidra.program.model.data.SignedCharDataType;
import ghidra.program.model.data.StructureDataType;
import ghidra.program.model.data.Undefined4DataType;
import ghidra.program.model.data.UnsignedCharDataType;
import ghidra.program.model.data.UnsignedIntegerDataType;
import ghidra.program.model.data.UnsignedLongLongDataType;
import ghidra.program.model.data.UnsignedShortDataType;
import ghidra.program.model.data.VoidDataType;
import ghidra.program.model.listing.CommentType;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Namespace;
import ghidra.program.model.symbol.SourceType;
import ghidra.program.model.symbol.Symbol;
import ghidra.program.model.symbol.SymbolTable;

public class ApplySymbols extends GhidraScript {
	static final String MARKER = "[sonicware-symbols]";
	static final List<String> LEVELS = List.of("speculative", "probable", "confirmed");

	private SymbolTable symbols;
	private DataTypeManager dtm;
	private int functionsCreated, functionsRenamed, labelsAdded, signaturesApplied, skipped, failures;
	private final List<String> signatureFailures = new ArrayList<>();

	@Override
	protected void run() throws Exception {
		String[] args = getScriptArgs();
		File file = args.length > 0 ? new File(args[0]) : askFile("sonicware-symbols/1 JSON", "Apply");
		int minLevel = 0;
		boolean signatures = false;
		for (int i = 1; i < args.length; i++) {
			if (args[i].startsWith("min=")) {
				minLevel = LEVELS.indexOf(args[i].substring(4));
				if (minLevel < 0) {
					throw new IllegalArgumentException("min= takes one of " + LEVELS);
				}
			}
			else if (args[i].equals("signatures")) {
				signatures = true;
			}
			else {
				throw new IllegalArgumentException("unknown option " + args[i]);
			}
		}
		JsonObject doc;
		try (FileReader reader = new FileReader(file)) {
			doc = JsonParser.parseReader(reader).getAsJsonObject();
		}
		if (!"sonicware-symbols/1".equals(doc.get("format").getAsString())) {
			throw new IllegalStateException(file + " is not a sonicware-symbols/1 file");
		}
		symbols = currentProgram.getSymbolTable();
		dtm = currentProgram.getDataTypeManager();
		JsonArray entries = doc.getAsJsonArray("symbols");
		verify(doc, entries);

		for (JsonElement element : entries) {
			monitor.checkCancelled();
			JsonObject s = element.getAsJsonObject();
			if (LEVELS.indexOf(s.get("confidence").getAsString()) < minLevel) {
				skipped++;
				continue;
			}
			try {
				if (s.get("kind").getAsString().equals("function")) {
					applyFunction(s, signatures);
				}
				else {
					applyData(s);
				}
			}
			catch (Exception e) {
				failures++;
				printerr(s.get("name").getAsString() + " at " + s.get("address").getAsString() + ": " + e);
			}
		}
		println(String.format("ApplySymbols: %d entries, %d skipped below min, %d functions created, " +
			"%d renamed, %d extra labels, %d signatures applied, %d signatures not applied, %d failures",
			entries.size(), skipped, functionsCreated, functionsRenamed, labelsAdded, signaturesApplied,
			signatureFailures.size(), failures));
		for (String f : signatureFailures) {
			println("  signature not applied: " + f);
		}
	}

	/** Refuse to touch a program whose bytes do not match every function prefix hash in the file. */
	private void verify(JsonObject doc, JsonArray entries) throws Exception {
		List<String> bad = new ArrayList<>();
		int checked = 0;
		for (JsonElement element : entries) {
			JsonObject s = element.getAsJsonObject();
			if (!s.has("prefix_sha256")) {
				continue;
			}
			Address a = toAddr(Long.decode(s.get("address").getAsString()));
			String want = s.get("prefix_sha256").getAsString();
			byte[] have = new byte[PREFIX_LEN];
			boolean ok;
			try {
				ok = currentProgram.getMemory().getBytes(a, have) == PREFIX_LEN && prefixHash(have).equals(want);
			}
			catch (Exception e) {
				ok = false;
			}
			if (!ok) {
				bad.add(s.get("name").getAsString() + " at " + a);
			}
			checked++;
		}
		JsonObject source = doc.getAsJsonObject("source");
		String what = source.get("file").getAsString() + " (sha256 " + source.get("sha256").getAsString() + ")";
		if (checked == 0 || !bad.isEmpty()) {
			throw new IllegalStateException(bad.size() + " of " + checked + " function prefixes do not match " +
				"the program, so it is not " + what + ". First: " + bad.subList(0, Math.min(5, bad.size())));
		}
		println("Verified " + checked + " function prefixes for " + what);
	}

	private void applyFunction(JsonObject s, boolean signatures) throws Exception {
		Address address = toAddr(Long.decode(s.get("address").getAsString()));
		String full = s.get("name").getAsString();
		List<String> parts = splitQualified(full);
		String leaf = parts.remove(parts.size() - 1);
		Function f = ensureFunction(address);
		if (f == null) {
			return;
		}
		setFunctionName(f, namespaceFor(parts), leaf);
		String prototype = s.has("prototype") ? s.get("prototype").getAsString() : null;
		setPlate(address, full, s, prototype != null ? "prototype: " + prototype : null);
		if (signatures && prototype != null) {
			applySignature(f, full, prototype);
		}
	}

	private void applyData(JsonObject s) throws Exception {
		Address address = toAddr(Long.decode(s.get("address").getAsString()));
		String full = s.get("name").getAsString();
		List<String> parts = splitQualified(full);
		String leaf = parts.remove(parts.size() - 1);
		label(address, leaf, namespaceFor(parts), true);
		if (currentProgram.getMemory().contains(address)) {
			setPlate(address, full, s, s.has("type") ? "type: " + s.get("type").getAsString() : null);
		}
	}

	private void setPlate(Address address, String name, JsonObject s, String line) {
		StringBuilder block = new StringBuilder(MARKER).append('\n')
			.append(name).append(" (").append(s.get("confidence").getAsString()).append(')');
		if (line != null) {
			block.append('\n').append(line);
		}
		for (JsonElement e : s.getAsJsonArray("evidence")) {
			block.append("\n- ").append(e.getAsString());
		}
		String old = currentProgram.getListing().getComment(CommentType.PLATE, address);
		String keep = "";
		if (old != null) {
			int at = old.indexOf(MARKER);
			keep = (at < 0 ? old : old.substring(0, at)).stripTrailing();
		}
		currentProgram.getListing().setComment(address, CommentType.PLATE,
			keep.isEmpty() ? block.toString() : keep + "\n\n" + block);
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

	/** Rename only default or analysis-generated names; otherwise keep the existing name and add a label. */
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
			label(f.getEntryPoint(), name, ns, false);
		}
	}

	private void label(Address address, String name, Namespace ns, boolean makePrimary) throws Exception {
		name = sanitize(name);
		Symbol existing = symbols.getSymbol(name, address, ns);
		if (existing == null) {
			existing = symbols.createLabel(address, name, ns, SourceType.IMPORTED);
			labelsAdded++;
		}
		if (makePrimary) {
			Symbol primary = symbols.getPrimarySymbol(address);
			if (primary == null || primary.getSource() != SourceType.USER_DEFINED) {
				existing.setPrimary();
			}
		}
	}

	private Namespace namespaceFor(List<String> parts) throws Exception {
		Namespace ns = currentProgram.getGlobalNamespace();
		for (String part : parts) {
			String p = sanitize(part);
			Namespace next = symbols.getNamespace(p, ns);
			ns = next != null ? next : symbols.createNameSpace(ns, p, SourceType.IMPORTED);
		}
		return ns;
	}

	// ---- Signatures -------------------------------------------------------------------------------

	private static final Map<String, DataType> BUILTIN = new HashMap<>();
	static {
		DataType u32 = UnsignedIntegerDataType.dataType;
		DataType s32 = IntegerDataType.dataType;
		for (String n : new String[] { "unsigned", "unsigned int", "uint32_t", "uint", "UINT", "DWORD", "size_t",
			"uintptr_t", "unsigned long" }) {
			BUILTIN.put(n, u32);
		}
		for (String n : new String[] { "int", "signed", "signed int", "int32_t", "long", "INT", "FRESULT",
			"DRESULT", "DSTATUS" }) {
			BUILTIN.put(n, s32);
		}
		for (String n : new String[] { "unsigned char", "uint8_t", "BYTE", "uchar" }) {
			BUILTIN.put(n, UnsignedCharDataType.dataType);
		}
		BUILTIN.put("char", CharDataType.dataType);
		BUILTIN.put("TCHAR", CharDataType.dataType);
		BUILTIN.put("signed char", SignedCharDataType.dataType);
		BUILTIN.put("int8_t", SignedCharDataType.dataType);
		for (String n : new String[] { "unsigned short", "uint16_t", "WORD", "WCHAR" }) {
			BUILTIN.put(n, UnsignedShortDataType.dataType);
		}
		BUILTIN.put("short", ShortDataType.dataType);
		BUILTIN.put("int16_t", ShortDataType.dataType);
		BUILTIN.put("long long", LongLongDataType.dataType);
		BUILTIN.put("int64_t", LongLongDataType.dataType);
		BUILTIN.put("unsigned long long", UnsignedLongLongDataType.dataType);
		BUILTIN.put("uint64_t", UnsignedLongLongDataType.dataType);
		BUILTIN.put("float", FloatDataType.dataType);
		BUILTIN.put("double", DoubleDataType.dataType);
		BUILTIN.put("bool", BooleanDataType.dataType);
		BUILTIN.put("void", VoidDataType.dataType);
	}

	private void applySignature(Function f, String name, String prototype) {
		try {
			FunctionDefinitionDataType def = reduce(prototype);
			ApplyFunctionSignatureCmd cmd = new ApplyFunctionSignatureCmd(f.getEntryPoint(), def,
				SourceType.IMPORTED, true, false, DataTypeConflictHandler.DEFAULT_HANDLER,
				FunctionRenameOption.NO_CHANGE);
			if (!cmd.applyTo(currentProgram, monitor)) {
				throw new IllegalStateException(cmd.getStatusMsg());
			}
			if (f.hasUnknownCallingConventionName()) {
				// the definition has no convention; use the compiler spec's default (C6000 EABI)
				f.setCallingConvention(currentProgram.getCompilerSpec().getDefaultCallingConvention().getName());
			}
			signaturesApplied++;
		}
		catch (Exception e) {
			signatureFailures.add(name + ": " + e.getMessage());
		}
	}

	/** Reduce a prototype note to a function definition, or throw if it does not reduce cleanly. */
	FunctionDefinitionDataType reduce(String prototype) {
		String p = prototype.replaceAll("/\\*.*?\\*/", " ").trim();
		int open = topLevelParen(p);
		if (open < 0 || !p.endsWith(")")) {
			throw new IllegalArgumentException("no parameter list");
		}
		String head = p.substring(0, open).trim();
		String params = p.substring(open + 1, p.length() - 1).trim();
		// head is "<return type> <name>"; the name is the last top-level token
		int cut = lastTopLevelSpaceOrStar(head);
		if (cut < 0) {
			throw new IllegalArgumentException("no return type");
		}
		FunctionDefinitionDataType def = new FunctionDefinitionDataType("f", dtm);
		def.setReturnType(type(head.substring(0, cut + 1)));
		List<ParameterDefinition> list = new ArrayList<>();
		int index = 0;
		for (String raw : splitTopLevel(params, ',')) {
			String a = raw.trim();
			if (a.isEmpty() || (a.equals("void") && index == 0 && params.trim().equals("void"))) {
				continue;
			}
			index++;
			if (a.equals("...")) {
				def.setVarArgs(true);
				continue;
			}
			String argName = "arg" + index;
			DataType t;
			if (a.equals("?")) {
				t = Undefined4DataType.dataType;
			}
			else if (a.contains("(*") || a.contains("std::function")) {
				t = PointerDataType.dataType;
				java.util.regex.Matcher m = java.util.regex.Pattern.compile("\\(\\*\\s*(\\w+)\\s*\\)").matcher(a);
				if (m.find()) {
					argName = m.group(1);
				}
				else {
					java.util.regex.Matcher n = java.util.regex.Pattern.compile("(\\w+)\\s*$").matcher(a);
					if (a.contains("std::function") && n.find()) {
						argName = n.group(1);
					}
				}
			}
			else {
				int c = lastTopLevelSpaceOrStar(a);
				String typeText = a;
				if (c >= 0 && !isTypeWord(a.substring(c + 1).trim())) {
					typeText = a.substring(0, c + 1);
					argName = a.substring(c + 1).trim();
				}
				t = type(typeText);
			}
			if (argName.equals("this")) {
				argName = "self";
			}
			list.add(new ParameterDefinitionImpl(sanitize(argName), t, null));
		}
		def.setArguments(list.toArray(new ParameterDefinition[0]));
		return def;
	}

	private DataType type(String text) {
		String t = text.replaceAll("\\b(const|volatile|struct|enum|union)\\b", " ").trim();
		int stars = 0;
		while (t.endsWith("*") || t.endsWith("&")) {
			stars++;
			t = t.substring(0, t.length() - 1).trim();
		}
		t = t.replaceAll("\\s+", " ");
		if (t.isEmpty() || t.contains("<") || t.contains("(")) {
			throw new IllegalArgumentException("type '" + text.trim() + "'");
		}
		DataType base = BUILTIN.get(t);
		if (base == null) {
			if (stars == 0) {
				base = Undefined4DataType.dataType;
			}
			else {
				base = placeholder(t);
			}
		}
		if (base instanceof VoidDataType && stars == 0) {
			return base;
		}
		for (int i = 0; i < stars; i++) {
			base = new PointerDataType(base, dtm);
		}
		return base;
	}

	/** An empty structure named after the type, in /sonicware (C++ scopes become sub-categories). */
	private DataType placeholder(String qualified) {
		List<String> parts = splitQualified(qualified);
		String leaf = sanitize(parts.remove(parts.size() - 1));
		CategoryPath path = new CategoryPath("/sonicware");
		for (String part : parts) {
			path = path.extend(sanitize(part));
		}
		DataType existing = dtm.getDataType(path, leaf);
		if (existing != null) {
			return existing;
		}
		return dtm.addDataType(new StructureDataType(path, leaf, 0, dtm), DataTypeConflictHandler.KEEP_HANDLER);
	}

	private static boolean isTypeWord(String w) {
		return BUILTIN.containsKey(w) || w.equals("long") || w.equals("short") || w.equals("int") ||
			w.equals("char") || w.endsWith("*");
	}

	private static int topLevelParen(String s) {
		int depth = 0;
		for (int i = 0; i < s.length(); i++) {
			char ch = s.charAt(i);
			if (ch == '<') depth++;
			else if (ch == '>') depth--;
			else if (ch == '(' && depth == 0) return i;
		}
		return -1;
	}

	private static int lastTopLevelSpaceOrStar(String s) {
		int depth = 0;
		for (int i = s.length() - 1; i >= 0; i--) {
			char ch = s.charAt(i);
			if (ch == '>' || ch == ')') depth++;
			else if (ch == '<' || ch == '(') depth--;
			else if (depth == 0 && (ch == ' ' || ch == '*' || ch == '&')) return i;
		}
		return -1;
	}

	private static List<String> splitTopLevel(String s, char sep) {
		List<String> out = new ArrayList<>();
		int depth = 0, start = 0;
		for (int i = 0; i < s.length(); i++) {
			char ch = s.charAt(i);
			if (ch == '<' || ch == '(' || ch == '{') depth++;
			else if (ch == '>' || ch == ')' || ch == '}') depth--;
			else if (depth == 0 && ch == sep) {
				out.add(s.substring(start, i));
				start = i + 1;
			}
		}
		out.add(s.substring(start));
		return out;
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

	static String sanitize(String name) {
		return name.replaceAll("\\s+", "_");
	}

	/** Bytes hashed per function entry; must match analysis/symfile.py. */
	static final int PREFIX_LEN = 16;

	/** analysis/symfile.py prefix_hash: SHA-256 of the bytes, first 128 bits as lowercase hex. */
	static String prefixHash(byte[] code) throws java.security.NoSuchAlgorithmException {
		byte[] digest = java.security.MessageDigest.getInstance("SHA-256").digest(code);
		StringBuilder out = new StringBuilder();
		for (int i = 0; i < 16; i++) {
			out.append(String.format("%02x", digest[i] & 0xff));
		}
		return out.toString();
	}
}
