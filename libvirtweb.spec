
%define         _pxeimages_root       /osinstall/nbp

Summary:       Web interface to display libvirt stats
Name:          libvirtweb
Version:       0.1
Release:       1
License:       GPL
Group:         Kernel
Source:        %{name}-%{version}.tar.gz
BuildRoot:     %{_tmppath}/%{name}-%{version}-build
BuildArch:     noarch
Requires:      python-cheetah

%description
This package provides a Python CGI script for displaying the status
of remote VMs using libvirt.

%prep
%setup -q

%build
mkdir -p %{buildroot}/var/www/cgi-bin/templates
cp  %{_topdir}/BUILD/%{name}-%{version}/virtweb.cgi.py %{buildroot}/var/www/cgi-bin
mkdir -p %{buildroot}/var/www/html/libvirtweb
cp -a %{_topdir}/BUILD/%{name}-%{version}/static/* %{buildroot}/var/www/html/libvirtweb
cp -a %{_topdir}/BUILD/%{name}-%{version}/templates %{buildroot}/var/www/cgi-bin


%files
%defattr(-,root,root)
/var/www/html/libvirtweb
/var/www/cgi-bin

%clean
rm -rf %{buildroot}

