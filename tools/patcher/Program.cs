// Usage: Patcher <input Il2CppInterop.Generator.dll> <output dll> [BepInEx\core folder]
// In Il2CppInterop.Generator.Extensions.CustomAttributeEx.Extract, the call
//   Enumerable.SingleOrDefault<CustomAttribute>(attrs, predicate)
// becomes
//   Enumerable.LastOrDefault<CustomAttribute>(attrs, predicate)
// so a member carrying the rebuild's leftover dumper tag plus Cpp2IL's fresh tag uses the
// fresh (last) one instead of throwing. Members with one tag behave exactly as before.
using Mono.Cecil;
using Mono.Cecil.Cil;

var (input, output) = (args[0], args[1]);
var resolver = new DefaultAssemblyResolver();
resolver.AddSearchDirectory(Path.GetDirectoryName(Path.GetFullPath(input)));
if (args.Length > 2) resolver.AddSearchDirectory(args[2]);  // BepInEx\core: the generator's dependencies
var module = ModuleDefinition.ReadModule(input, new ReaderParameters { AssemblyResolver = resolver });

var type = module.GetType("Il2CppInterop.Generator.Extensions.CustomAttributeEx")
           ?? throw new Exception("CustomAttributeEx not found");
var extract = type.Methods.Single(m => m.Name == "Extract");
int patched = 0;
foreach (var ins in extract.Body.Instructions)
{
    if (ins.OpCode != OpCodes.Call || ins.Operand is not GenericInstanceMethod gim) continue;
    if (gim.ElementMethod.Name != "SingleOrDefault" || gim.ElementMethod.Parameters.Count != 2) continue;
    if (gim.GenericArguments[0].Name != "CustomAttribute") continue; // leave the NamedArguments lookup alone

    var single = gim.ElementMethod;
    var last = new MethodReference("LastOrDefault", single.ReturnType, single.DeclaringType)
    {
        HasThis = single.HasThis, ExplicitThis = single.ExplicitThis, CallingConvention = single.CallingConvention,
    };
    var gp = new GenericParameter("TSource", last);
    last.GenericParameters.Add(gp);
    last.ReturnType = gp;
    // IEnumerable<TSource>, Func<TSource, bool> - rebuilt against the new method's own generic parameter
    var p0 = (GenericInstanceType)single.Parameters[0].ParameterType;
    var p1 = (GenericInstanceType)single.Parameters[1].ParameterType;
    var en = new GenericInstanceType(p0.ElementType); en.GenericArguments.Add(gp);
    var fn = new GenericInstanceType(p1.ElementType); fn.GenericArguments.Add(gp); fn.GenericArguments.Add(p1.GenericArguments[1]);
    last.Parameters.Add(new ParameterDefinition(en));
    last.Parameters.Add(new ParameterDefinition(fn));

    var inst = new GenericInstanceMethod(last);
    inst.GenericArguments.Add(gim.GenericArguments[0]);
    ins.Operand = module.ImportReference(inst);
    patched++;
}
if (patched != 1) throw new Exception($"expected exactly 1 call to patch, found {patched}");
module.Write(output);
Console.WriteLine($"patched {patched} call: SingleOrDefault<CustomAttribute> -> LastOrDefault<CustomAttribute>");
Console.WriteLine($"written {output}");
