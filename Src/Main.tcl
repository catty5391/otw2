wipe
if { [file exists ../output] == 0 } {
    file mkdir ../output
}

puts "System"
model basic -ndm 3 -ndf 6

puts "Node"
source ../Src/Node.tcl

puts "Mass"
source ../Src/Mass.tcl

puts "Restraint"
source ../Src/Fix.tcl

puts "Material"
source ../Src/Material.tcl

puts "Section"
source ../Src/Section.tcl

puts "Transformation"
source ../Src/geomtransf.tcl

puts "Element"
source ../Src/Element.tcl

puts "Timeseries"
source ../fluctuate_wind_simulate/wind_press/wind_force_tcl/timeseries.tcl

puts "Pattern"
source ../fluctuate_wind_simulate/wind_press/wind_force_tcl/pattern.tcl

recorder Node -file ../output/Node_accel.out -time -node 350  -dof 2 accel

recorder Node -file ../output/Node_velocity.out -time -node 350  -dof 2 vel

recorder Node -file ../output/Node_disp.out -time -node 350  -dof 2 disp

recorder Drift -file ../output/drift.out -time -iNode 350 -jNode 510 -dof 2 -perpDirn 3






# set temp [eigen 1]
# scan $temp "%e"  w1s
# set w1 [expr sqrt($w1s)]
# puts "第一阶频率   f: [expr $w1/6.28]"
# set ksi  0.02
# set a0 0
# set a1 [expr $ksi*2.0/$w1]
# rayleigh          $a0            0.0            $a1                0.0
# wipeAnalysis;					                                                              
constraints Plain;     				                       
numberer RCM;					                       
system BandGeneral;				
test NormDispIncr 1.0e-3 40 2;			
algorithm KrylovNewton;	
integrator Newmark 0.5 0.25				
		                                                               
analysis Transient;	

analyze 8192 8.333333333333332871e-02




# loadConst -time 0.0


# puts "Force"
# source ../normal_force/force3.tcl
# integrator LoadControl 0.0001;
# analyze 2000;


puts "over"