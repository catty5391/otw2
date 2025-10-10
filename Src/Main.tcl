wipe
if { [file exists ../output] == 0 } {
    file mkdir ../output
}

puts "System"
model basic -ndm 3 -ndf 3

puts "Node"
source Node.tcl

puts "Mass"
source Mass.tcl

puts "Restraint"
source Fix.tcl

puts "Material"
source Material.tcl

puts "Section"
source Section.tcl

# puts "Transformation"
# source geomtransf.tcl

puts "Element"
source Element.tcl

recorder Node -file ../output/Node_accel.out -time -node 172  -dof 2 accel

recorder Node -file ../output/Node_velocity.out -time -node 172  -dof 2 vel

recorder Node -file ../output/Node_disp.out -time -node 172  -dof 2 disp

recorder Drift -file ../output/drift.out -time -iNode 172 -jNode 732 -dof 2 -perpDirn 3

recorder Element -file ../output/stress.out -time -ele 344 section 1 fiberData 
#node 1492 3.28 -3.28 3.2





set temp [eigen 1]
scan $temp "%e"  w1s
set w1 [expr sqrt($w1s)]
puts "第一阶频率   f: [expr $w1/6.28]"
set ksi  0.02
set a0 0
set a1 [expr $ksi*2.0/$w1]
rayleigh          $a0            0.0            $a1                0.0
wipeAnalysis;					                                                              
constraints Plain;     				                       
numberer RCM;					                       
system BandGeneral;				
test NormDispIncr 1.0e-3 40 2;			
algorithm KrylovNewton;					
		                                                               
analysis Static;	
puts "Force"
source ../normal_force/force.tcl


integrator DisplacementControl 172 2 0.01

analyze 200




# loadConst -time 0.0


# puts "Force"
# source ../normal_force/force3.tcl
# integrator LoadControl 0.0001;
# analyze 2000;


puts "over"