// Same steps as BepInEx be.793 Il2CppInteropManager (RunCpp2Il + RunIl2CppInteropGenerator),
// but writing into a temp folder, with the patched generator referenced. Read-only on the game.
using System.Diagnostics;
using AssetRipper.Primitives;
using Cpp2IL.Core;
using Cpp2IL.Core.Api;
using Cpp2IL.Core.InstructionSets;
using Cpp2IL.Core.OutputFormats;
using Cpp2IL.Core.ProcessingLayers;
using Il2CppInterop.Generator;
using Il2CppInterop.Generator.Runners;
using LibCpp2IL;

var game = Environment.GetEnvironmentVariable("TAC_GAME") ?? throw new Exception("set TAC_GAME to the game folder");
var outDir = args.Length > 0 ? args[0] : Path.Combine(Path.GetTempPath(), "tac_interop_test");
if (Directory.Exists(outDir)) Directory.Delete(outDir, true);
Directory.CreateDirectory(outDir);

InstructionSetRegistry.RegisterInstructionSet<X86InstructionSet>(DefaultInstructionSets.X86_32);
InstructionSetRegistry.RegisterInstructionSet<X86InstructionSet>(DefaultInstructionSets.X86_64);
LibCpp2IlBinaryRegistry.RegisterBuiltInBinarySupport();
Cpp2IL.Core.Logging.Logger.WarningLog += (m, s) => { };
Cpp2IL.Core.Logging.Logger.InfoLog += (m, s) => { };

var sw = Stopwatch.StartNew();
Cpp2IlApi.InitializeLibCpp2Il(Path.Combine(game, "GameAssembly.dll"),
    Path.Combine(game, @"TagaReconstruction_Data\il2cpp_data\Metadata\global-metadata.dat"),
    UnityVersion.Parse("6000.3.24f1"), false);
var layers = new List<Cpp2IlProcessingLayer> { new AttributeInjectorProcessingLayer() };
foreach (var l in layers) l.PreProcess(Cpp2IlApi.CurrentAppContext, layers);
foreach (var l in layers) l.Process(Cpp2IlApi.CurrentAppContext);
var assemblies = new AsmResolverDllOutputFormatDefault().BuildAssemblies(Cpp2IlApi.CurrentAppContext);
LibCpp2IlMain.Reset();
Cpp2IlApi.CurrentAppContext = null;
Console.WriteLine($"Cpp2IL done in {sw.Elapsed}, {assemblies.Count} assemblies");

sw.Restart();
var opts = new GeneratorOptions
{
    GameAssemblyPath = Path.Combine(game, "GameAssembly.dll"),   // ScanMethodRefs = true in BepInEx.cfg
    Source = assemblies,
    OutputDir = outDir,
    UnityBaseLibsDir = Path.Combine(game, @"BepInEx\unity-libs"),
};
Il2CppInteropGenerator.Create(opts).AddInteropAssemblyGenerator().Run();
var files = Directory.GetFiles(outDir, "*.dll");
Console.WriteLine($"Generator done in {sw.Elapsed}: {files.Length} interop assemblies in {outDir}");
foreach (var f in files.Where(f => Path.GetFileName(f) is "Assembly-CSharp.dll" or "UnityEngine.UI.dll" or "UnityEngine.CoreModule.dll"))
    Console.WriteLine($"   {Path.GetFileName(f)}  {new FileInfo(f).Length:N0} bytes");
